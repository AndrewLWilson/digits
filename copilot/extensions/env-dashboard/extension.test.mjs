import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// Runs in a child Node process. Fakes timers, tmux and the Copilot SDK, imports
// the extension, runs the scenario and prints a JSON summary.
const DRIVER_PRELUDE = String.raw`
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";

const at = (seconds) => new Date(seconds * 1000).toISOString();
const ev = (type, seconds, data = {}, extra = {}) => ({ type, timestamp: at(seconds), data, ...extra });
const settle = async () => { for (let i = 0; i < 30; i += 1) await new Promise((r) => setImmediate(r)); };

const record = { publishes: [], folders: [], delays: [], tmuxCalls: [], joinOptionKeys: null, tools: null };
const timers = [];
globalThis.setTimeout = (fn, ms) => {
  const handle = { fn, ms, done: false, unrefed: false, unref() { this.unrefed = true; return this; } };
  timers.push(handle);
  record.delays.push(ms);
  return handle;
};
globalThis.clearTimeout = (handle) => { if (handle) handle.done = true; };
const fire = async () => {
  const due = timers.filter((t) => !t.done);
  for (const t of due) { t.done = true; t.fn(); }
  await settle();
};

const ctl = {
  history: [ev("user.message", 100)],
  activity: true,
  processing: true,
  tasks: [],
  pending: [],
  snapshot: { isRemote: false, workspacePath: "/sessions/abc" },
  fail: {},
  gate: {},
  owner: null,
  failPublish: () => false,
  joinError: null,
  counts: { getEvents: 0, activity: 0, pendingRequests: 0, isProcessing: 0, tasks: 0, snapshot: 0 },
  onEvent: null,
};

childProcess.execFileSync = (file, args) => {
  if (file !== "tmux" || args[0] !== "-S") throw new Error("unexpected command " + file);
  record.tmuxCalls.push(args.slice(2));
  const commands = [[]];
  for (const arg of args.slice(2)) {
    if (arg === ";") commands.push([]); else commands[commands.length - 1].push(arg);
  }
  if (commands[0][0] === "display-message") return (ctl.owner ?? String(process.pid)) + "\n";
  const valueOf = (option) => {
    for (const command of commands) {
      const i = command.indexOf(option);
      if (command[0] === "set-option" && i >= 0) return command.includes("-u") ? null : command[i + 1];
    }
    return undefined;
  };
  const label = valueOf("@env-copilot-state");
  if (label !== undefined) {
    const entry = { label, since: valueOf("@env-copilot-since") };
    const took = valueOf("@env-copilot-took");
    if (took) entry.took = took;
    if (ctl.failPublish(entry)) throw new Error("simulated publish failure");
    record.publishes.push(entry);
  }
  const folder = valueOf("@env-session-dir");
  if (folder !== undefined) record.folders.push(folder);
  return "";
};
syncBuiltinESMExports();

async function call(name, answer) {
  ctl.counts[name] += 1;
  if (ctl.gate[name]) { const gate = ctl.gate[name]; delete ctl.gate[name]; await gate; }
  if (ctl.fail[name] > 0) { ctl.fail[name] -= 1; throw new Error("simulated " + name + " failure"); }
  return answer();
}

const session = {
  getEvents: () => call("getEvents", () => ctl.history.slice()),
  rpc: {
    metadata: {
      activity: () => call("activity", () => ({ hasActiveWork: ctl.activity })),
      isProcessing: () => call("isProcessing", () => ({ processing: ctl.processing })),
      snapshot: () => call("snapshot", () => ctl.snapshot),
    },
    permissions: { pendingRequests: () => call("pendingRequests", () => ({ items: ctl.pending.map((requestId) => ({ requestId })) })) },
    tasks: { list: () => call("tasks", () => ({ tasks: ctl.tasks })) },
  },
};

globalThis.__digitsJoinSession = async (options) => {
  record.joinOptionKeys = Object.keys(options);
  record.tools = options.tools ?? null;
  ctl.onEvent = options.onEvent;
  if (ctl.joinError) throw new Error(ctl.joinError);
  return session;
};

const emit = async (event) => {
  if (event.type === "user.message") ctl.history.push(event);
  ctl.onEvent(event);
  await settle();
};
`;

const DRIVER_RUN = String.raw`
let importError = null;
try { await import("./extension.mjs"); } catch (error) { importError = error.message; }
await settle();
if (!importError) await body();
await settle();
process.stdout.write(JSON.stringify({ ...record, importError, counts: ctl.counts, timers: timers.map((t) => ({ ms: t.ms, unrefed: t.unrefed })) }));
`;

function runScenario({ setup = "", body = "", env = {} } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "digits-dashboard-"));
  try {
    copyFileSync(join(HERE, "extension.mjs"), join(dir, "extension.mjs"));
    copyFileSync(join(HERE, "state.mjs"), join(dir, "state.mjs"));
    const pkg = join(dir, "node_modules", "@github", "copilot-sdk");
    mkdirSync(pkg, { recursive: true });
    writeFileSync(
      join(pkg, "package.json"),
      JSON.stringify({ name: "@github/copilot-sdk", type: "module", exports: { "./extension": "./extension.mjs" } }),
    );
    writeFileSync(
      join(pkg, "extension.mjs"),
      "export function joinSession(options) { return globalThis.__digitsJoinSession(options); }\n",
    );
    const driver = `${DRIVER_PRELUDE}\n${setup}\nconst body = async () => {\n${body}\n};\n${DRIVER_RUN}`;
    writeFileSync(join(dir, "driver.mjs"), driver);
    const childEnv = { ...process.env, TMUX: "/synthetic-tmux,1,0", TMUX_PANE: "%1", ...env };
    for (const [key, value] of Object.entries(childEnv)) if (value === undefined) delete childEnv[key];
    const result = spawnSync(process.execPath, ["driver.mjs"], { cwd: dir, env: childEnv, encoding: "utf8", timeout: 20000 });
    assert.equal(result.status, 0, `driver failed: ${result.stderr}`);
    return { ...JSON.parse(result.stdout), stderr: result.stderr };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const labels = (summary) => summary.publishes.map((p) => p.label);
const last = (summary) => summary.publishes[summary.publishes.length - 1];

test("20: every initialisation failure shows UNKNOWN then recovers with backoff", () => {
  const cases = [
    { name: "history", setup: "ctl.fail.getEvents = 2;", fires: 2, delays: [1000, 2000], final: "WORKING" },
    { name: "activity", setup: "ctl.fail.activity = 1;", fires: 1, delays: [1000], final: "WORKING" },
    {
      name: "pending permissions",
      setup: "ctl.fail.pendingRequests = 1; ctl.pending = ['held'];",
      fires: 1,
      delays: [1000],
      final: "NEEDS YOU",
    },
    { name: "isProcessing", setup: "ctl.fail.isProcessing = 1;", fires: 1, delays: [1000], final: "WORKING" },
    { name: "tasks", setup: "ctl.fail.tasks = 1;", fires: 1, delays: [1000], final: "WORKING" },
    {
      name: "first publish",
      setup: "let failed = false; ctl.failPublish = (p) => { if (failed || p.label === 'UNKNOWN') return false; failed = true; return true; };",
      fires: 1,
      delays: [1000],
      final: "WORKING",
    },
  ];
  for (const item of cases) {
    const summary = runScenario({ setup: item.setup, body: "for (let i = 0; i < " + item.fires + "; i += 1) await fire();" });
    assert.equal(summary.publishes[0].label, "UNKNOWN", item.name);
    assert.match(summary.stderr, /Environment dashboard update failed/, item.name);
    assert.equal(last(summary).label, item.final, item.name);
    assert.deepEqual(summary.delays, item.delays, item.name);
    assert.ok(summary.timers.every((t) => t.unrefed), item.name);
  }
});

test("21: events while tracking has failed are replayed after the retry", () => {
  const summary = runScenario({
    setup: "let armed = false; ctl.failPublish = (p) => { if (armed && p.label !== 'UNKNOWN') { armed = false; return true; } return false; };",
    body: `
      armed = true;
      await emit(ev("user.message", 200, { delivery: "idle" }));
      await emit(ev("permission.requested", 201, { requestId: "perm" }));
      await fire();
      await emit(ev("permission.completed", 202, { requestId: "perm" }));
    `,
  });
  assert.deepEqual(labels(summary), ["WORKING", "UNKNOWN", "NEEDS YOU", "WORKING"]);
  assert.equal(last(summary).since, "200");
  assert.equal(summary.counts.getEvents, 2);
});

test("22: a failed post-idle reconcile does not leave tracking stuck", () => {
  const summary = runScenario({
    body: `
      ctl.activity = false; ctl.processing = false; ctl.fail.activity = 1;
      await emit(ev("session.idle", 200));
      await fire();
    `,
  });
  assert.deepEqual(labels(summary), ["WORKING", "YOUR TURN", "UNKNOWN", "YOUR TURN"]);
});

test("23: a stale reconcile answer never finishes a newer turn", () => {
  const summary = runScenario({
    body: `
      let release;
      ctl.gate.activity = new Promise((resolve) => { release = resolve; });
      ctl.activity = false; ctl.processing = false;
      await emit(ev("session.idle", 200));
      await emit(ev("user.message", 300, { delivery: "idle" }));
      release();
      await settle();
    `,
  });
  assert.deepEqual(last(summary), { label: "WORKING", since: "300" });
  assert.deepEqual(summary.delays, []);
});

test("24: a failing joinSession shows UNKNOWN and fails the import", () => {
  const summary = runScenario({ setup: "ctl.joinError = 'join exploded';" });
  assert.deepEqual(summary.publishes, [{ label: "UNKNOWN", since: "" }]);
  assert.equal(summary.importError, "join exploded");
  assert.deepEqual(summary.delays, []);
});

const attachedShell = "{ type: 'shell', status: 'running', attachmentMode: 'attached' }";

test("25: an attached shell with an idle model is WATCHING", () => {
  for (const activity of [true, false]) {
    const summary = runScenario({
      setup: `ctl.tasks = [${attachedShell}]; ctl.processing = false; ctl.activity = ${activity};`,
      body: `
        ctl.tasks = []; ctl.activity = false;
        await emit(ev("session.background_tasks_changed", 150));
      `,
    });
    assert.deepEqual(summary.publishes[0], { label: "WATCHING", since: "100" });
    assert.equal(last(summary).label, "YOUR TURN");
    assert.notEqual(last(summary).since, "");
    assert.equal(summary.counts.tasks, 2);
  }
});

test("26: an attached shell while processing is WORKING until the model idles", () => {
  const summary = runScenario({
    setup: `ctl.tasks = [${attachedShell}];`,
    body: `
      ctl.processing = false;
      await emit(ev("assistant.idle", 200));
      ctl.processing = true;
      await emit(ev("user.message", 300));
    `,
  });
  assert.deepEqual(labels(summary), ["WORKING", "WATCHING", "WORKING"]);
  assert.deepEqual(last(summary), { label: "WORKING", since: "100" });
});

test("27: a detached shell does not count", () => {
  const summary = runScenario({
    setup: "ctl.tasks = [{ type: 'shell', status: 'running', attachmentMode: 'detached' }]; ctl.processing = false;",
  });
  assert.equal(last(summary).label, "WORKING");
});

test("28: a failed post-idle task query while watching recovers", () => {
  const summary = runScenario({
    setup: `ctl.tasks = [${attachedShell}]; ctl.processing = false;`,
    body: `
      ctl.activity = false; ctl.fail.tasks = 1;
      await emit(ev("session.idle", 120));
      await fire();
    `,
  });
  assert.deepEqual(labels(summary), ["WATCHING", "UNKNOWN", "WATCHING"]);
  assert.equal(last(summary).since, "100");
});

const backgroundAgent = "{ type: 'agent', status: 'running', toolCallId: 'bg', executionMode: 'background' }";

test("29: a background agent with an idle model is SUBAGENTS", () => {
  const summary = runScenario({
    setup: `ctl.tasks = [${backgroundAgent}]; ctl.processing = false;`,
    body: `
      ctl.tasks = [{ type: 'agent', status: 'idle', toolCallId: 'bg', executionMode: 'background' }];
      ctl.activity = false;
      await emit(ev("session.background_tasks_changed", 150));
    `,
  });
  assert.deepEqual(summary.publishes[0], { label: "SUBAGENTS", since: "100" });
  assert.equal(last(summary).label, "YOUR TURN");
});

test("30: background child outliving the parent turn", () => {
  const summary = runScenario({
    body: `
      await emit(ev("subagent.started", 101, { toolCallId: "bg", executionMode: "background" }));
      ctl.tasks = [${backgroundAgent}];
      ctl.activity = false; ctl.processing = false;
      await emit(ev("assistant.idle", 102));
      ctl.tasks = [${backgroundAgent}, ${attachedShell}];
      await emit(ev("session.background_tasks_changed", 103));
      ctl.tasks = [${backgroundAgent}];
      await emit(ev("session.background_tasks_changed", 104));
      ctl.tasks = [];
      await emit(ev("subagent.completed", 105, { toolCallId: "bg" }));
      await emit(ev("session.idle", 106));
    `,
  });
  assert.deepEqual(summary.publishes, [
    { label: "WORKING", since: "100" },
    { label: "SUBAGENTS", since: "100" },
    { label: "YOUR TURN", since: "105", took: "5" },
  ]);
});

test("31: agents while processing and unattached shells are WORKING", () => {
  for (const setup of [
    `ctl.tasks = [${backgroundAgent}]; ctl.processing = true;`,
    "ctl.tasks = [{ type: 'shell', status: 'running' }]; ctl.processing = false;",
  ]) {
    assert.equal(last(runScenario({ setup })).label, "WORKING", setup);
  }
});

test("32: a failed post-idle task query while SUBAGENTS recovers", () => {
  const summary = runScenario({
    setup: `ctl.tasks = [${backgroundAgent}]; ctl.processing = false;`,
    body: `
      ctl.activity = false; ctl.fail.tasks = 1;
      await emit(ev("assistant.idle", 120));
      await fire();
    `,
  });
  assert.deepEqual(labels(summary), ["SUBAGENTS", "UNKNOWN", "SUBAGENTS"]);
  assert.equal(last(summary).since, "100");
});

test("33: a sync child spawned by a task tool", () => {
  const summary = runScenario({
    body: `
      await emit(ev("tool.execution_start", 101, { toolCallId: "spawn", toolName: "task" }));
      ctl.tasks = [{ type: 'agent', status: 'running', toolCallId: 'spawn', executionMode: 'sync' }];
      await emit(ev("subagent.started", 102, { toolCallId: "spawn", executionMode: "sync" }, { agentId: "kid" }));
      ctl.tasks = [];
      await emit(ev("subagent.completed", 103, { toolCallId: "spawn" }, { agentId: "kid" }));
      await emit(ev("tool.execution_complete", 104, { toolCallId: "spawn" }));
      ctl.activity = false; ctl.processing = false;
      await emit(ev("session.idle", 105));
    `,
  });
  assert.deepEqual(summary.publishes, [
    { label: "WORKING", since: "100" },
    { label: "SUBAGENTS", since: "100" },
    { label: "WORKING", since: "100" },
    { label: "YOUR TURN", since: "105", took: "5" },
  ]);
});

test("34: the session folder is published once after a successful sync", () => {
  const summary = runScenario({ setup: "ctl.fail.getEvents = 2;", body: "await fire(); await fire();" });
  assert.deepEqual(summary.folders, ["/sessions/abc"]);
  assert.equal(summary.counts.snapshot, 1);
});

test("35: a remote session unsets the folder", () => {
  const summary = runScenario({ setup: "ctl.snapshot = { isRemote: true, workspacePath: '/sessions/abc' };" });
  assert.deepEqual(summary.folders, [null]);
});

test("36: a failed folder snapshot is not a tracking failure", () => {
  const summary = runScenario({ setup: "ctl.fail.snapshot = 1;" });
  assert.deepEqual(summary.folders, []);
  assert.equal(last(summary).label, "WORKING");
  assert.deepEqual(summary.delays, []);
  assert.match(summary.stderr, /could not publish the session folder/);
  assert.doesNotMatch(summary.stderr, /Environment dashboard update failed/);
});

test("37: consecutive runs report their own durations and register no tools", () => {
  const summary = runScenario({
    body: `
      ctl.activity = false; ctl.processing = false;
      await emit(ev("session.idle", 352));
      await emit(ev("user.message", 400, { delivery: "idle" }));
      await emit(ev("session.idle", 405));
    `,
  });
  assert.ok(summary.tools === null || summary.tools.length === 0);
  assert.deepEqual(summary.joinOptionKeys, ["onEvent"]);
  assert.deepEqual(summary.publishes, [
    { label: "WORKING", since: "100" },
    { label: "YOUR TURN", since: "352", took: "252" },
    { label: "WORKING", since: "400" },
    { label: "YOUR TURN", since: "405", took: "5" },
  ]);
});

test("84: without tmux or with a malformed pane the extension stays silent", () => {
  for (const env of [{ TMUX: undefined }, { TMUX_PANE: "1" }, { TMUX_PANE: "%x" }, { TMUX: "/only-two,1" }]) {
    const summary = runScenario({
      env,
      body: `
        await emit(ev("permission.requested", 101, { requestId: "p" }));
        await emit(ev("session.idle", 102));
      `,
    });
    assert.deepEqual(summary.joinOptionKeys, ["onEvent"], JSON.stringify(env));
    assert.deepEqual(summary.tmuxCalls, [], JSON.stringify(env));
    assert.equal(summary.counts.getEvents, 0, JSON.stringify(env));
  }
});

test("85: retry delays double to a 30 s cap and reset after success", () => {
  const summary = runScenario({
    setup: "ctl.fail.getEvents = 7;",
    body: `
      for (let i = 0; i < 7; i += 1) await fire();
      ctl.fail.activity = 1;
      await emit(ev("session.idle", 200));
    `,
  });
  assert.deepEqual(summary.delays, [1000, 2000, 4000, 8000, 16000, 30000, 30000, 1000]);
  assert.ok(summary.publishes.some((p) => p.label === "WORKING"));
});

test("86: exit cleanup only clears options this process owns", () => {
  const foreign = runScenario({ body: "ctl.owner = '999999999'; const before = record.tmuxCalls.length; process.emit('exit', 0); record.after = record.tmuxCalls.slice(before);" });
  // Only the ownership query ran.
  assert.equal(foreign.after.length, 1);
  assert.equal(foreign.after[0][0], "display-message");

  const own = runScenario({ body: "const before = record.tmuxCalls.length; process.emit('exit', 0); record.after = record.tmuxCalls.slice(before);" });
  assert.equal(own.after.length, 2);
  const unset = own.after[1];
  for (const option of ["@env-copilot-state", "@env-copilot-since", "@env-copilot-took", "@env-session-dir", "@env-dashboard-owner"]) {
    const index = unset.indexOf(option);
    assert.ok(index > 0, option);
    assert.deepEqual(unset.slice(index - 4, index), ["set-option", "-pu", "-t", "%1"]);
  }
  assert.deepEqual(unset.slice(-2), ["refresh-client", "-S"]);
});

test("extension passes a syntax check", () => {
  execFileSync(process.execPath, ["--check", join(HERE, "extension.mjs")]);
});

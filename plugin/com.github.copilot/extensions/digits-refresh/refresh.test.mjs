import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  ORDER,
  createRefreshExtension,
  createRefresher,
  fingerprint,
  isCodeFile,
  listFiles,
  sessionIsIdle,
} from "./refresh.mjs";

function tempDir(t) {
  const dir = mkdtempSync(join(tmpdir(), "digits-refresh-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function fixture(t, { failing = [] } = {}) {
  const dir = tempDir(t);
  const files = {};
  for (const name of ORDER) {
    files[name] = join(dir, `${name}.txt`);
    writeFileSync(files[name], "v1");
  }
  const reloads = [];
  const notes = [];
  let clock = 0;
  let idle = true;
  const groups = {};
  for (const name of ORDER) {
    groups[name] = {
      files: () => [files[name]],
      reload: async () => {
        reloads.push(name);
        if (failing.includes(name)) throw new Error(`${name} broke`);
      },
    };
  }
  const refresher = createRefresher({
    groups,
    isIdle: async () => idle,
    notify: async (text, level = "info") => notes.push({ text, level }),
    now: () => clock,
    settleMs: 3000,
  });
  return {
    files,
    reloads,
    notes,
    refresher,
    edit: (name, text) => writeFileSync(files[name], text),
    setIdle: (value) => {
      idle = value;
    },
    at: (time) => {
      clock = time;
      return refresher.check();
    },
  };
}

test("ORDER keeps extensions last", () => {
  assert.deepEqual(ORDER, ["instructions", "skills", "extensions"]);
});

test("unchanged files never reload", async (t) => {
  const f = fixture(t);
  assert.deepEqual(await f.at(10000), []);
  assert.deepEqual(f.reloads, []);
  assert.deepEqual(f.notes, []);
});

test("a change reloads once after settling", async (t) => {
  const f = fixture(t);
  f.edit("skills", "v2");
  assert.deepEqual(await f.at(1000), []);
  assert.deepEqual(await f.at(3000), []);
  assert.deepEqual(await f.at(4000), ["skills"]);
  assert.deepEqual(await f.at(9000), []);
  assert.deepEqual(f.reloads, ["skills"]);
  assert.match(f.notes[0].text, /refreshing skills in place/);
  assert.equal(f.notes[0].level, "info");
  assert.equal(f.notes.length, 1);
});

test("a busy chat defers the reload", async (t) => {
  const f = fixture(t);
  f.edit("instructions", "v2");
  f.setIdle(false);
  assert.deepEqual(await f.at(0), []);
  assert.deepEqual(await f.at(5000), []);
  assert.deepEqual(f.reloads, []);
  f.setIdle(true);
  assert.deepEqual(await f.at(6000), ["instructions"]);
  assert.deepEqual(f.reloads, ["instructions"]);
});

test("extensions reload last", async (t) => {
  const f = fixture(t);
  for (const name of ["extensions", "skills", "instructions"]) f.edit(name, "v2");
  assert.deepEqual(await f.at(0), []);
  assert.deepEqual(await f.at(3000), ["instructions", "skills", "extensions"]);
  assert.deepEqual(f.reloads, ["instructions", "skills", "extensions"]);
  assert.match(f.notes[0].text, /refreshing instructions, skills, extensions in place/);
});

test("an edit reverted before settling causes no reload", async (t) => {
  const f = fixture(t);
  f.edit("skills", "v2");
  assert.deepEqual(await f.at(0), []);
  f.edit("skills", "v1");
  assert.deepEqual(await f.at(5000), []);
  assert.deepEqual(f.reloads, []);
});

test("a failing reload warns once and is not retried", async (t) => {
  const f = fixture(t, { failing: ["instructions"] });
  f.edit("instructions", "v2");
  f.edit("skills", "v2");
  await f.at(0);
  assert.deepEqual(await f.at(3000), ["instructions", "skills"]);
  assert.deepEqual(await f.at(9000), []);
  assert.deepEqual(f.reloads, ["instructions", "skills"]);
  const last = f.notes.at(-1);
  assert.equal(last.level, "warning");
  assert.match(last.text, /\/restart/);
  assert.match(last.text, /instructions: instructions broke/);
  assert.equal(f.notes.filter((n) => n.level === "warning").length, 1);
});

test("a further edit restarts the stability window", async (t) => {
  const f = fixture(t);
  f.edit("skills", "v2");
  assert.deepEqual(await f.at(0), []);
  f.edit("skills", "v3");
  assert.deepEqual(await f.at(2000), []);
  assert.deepEqual(await f.at(4000), []);
  assert.deepEqual(await f.at(5000), ["skills"]);
});

test("an unchanged pending value keeps its first-seen time", async (t) => {
  const f = fixture(t);
  f.edit("skills", "v2");
  await f.at(0);
  await f.at(2000);
  assert.deepEqual(await f.at(3000), ["skills"]);
});

test("overlapping checks share one run", async (t) => {
  const dir = tempDir(t);
  const file = join(dir, "skill.txt");
  writeFileSync(file, "v1");
  let idleCalls = 0;
  let release;
  const gate = new Promise((r) => {
    release = r;
  });
  let clock = 0;
  const refresher = createRefresher({
    groups: { skills: { files: () => [file], reload: async () => {} } },
    isIdle: async () => {
      idleCalls += 1;
      await gate;
      return true;
    },
    notify: async () => {},
    now: () => clock,
  });
  writeFileSync(file, "v2");
  await refresher.check();
  clock = 3000;
  const first = refresher.check();
  const second = refresher.check();
  assert.equal(first, second);
  release();
  const [a, b] = await Promise.all([first, second]);
  assert.deepEqual(a, ["skills"]);
  assert.deepEqual(b, ["skills"]);
  assert.equal(idleCalls, 1);
});

test("fingerprint ignores order and notices changes", (t) => {
  const dir = tempDir(t);
  const a = join(dir, "a");
  const b = join(dir, "b");
  writeFileSync(a, "one");
  writeFileSync(b, "two");
  const base = fingerprint([a, b]);
  assert.match(base, /^[0-9a-f]{64}$/);
  assert.equal(fingerprint([b, a, a]), base);
  assert.equal(fingerprint([a, b]), base);
  assert.notEqual(fingerprint([a]), base);
  writeFileSync(b, "three");
  assert.notEqual(fingerprint([a, b]), base);
  const missing = join(dir, "missing");
  const withMissing = fingerprint([a, missing]);
  writeFileSync(missing, "");
  assert.notEqual(fingerprint([a, missing]), withMissing);
});

test("listFiles handles missing roots, skips hidden and node_modules, ignores links", (t) => {
  const dir = tempDir(t);
  assert.deepEqual(listFiles(join(dir, "absent"), () => true), []);
  mkdirSync(join(dir, "ext", "nested"), { recursive: true });
  mkdirSync(join(dir, "ext", "node_modules"), { recursive: true });
  mkdirSync(join(dir, "ext", ".hidden"), { recursive: true });
  writeFileSync(join(dir, "ext", "extension.mjs"), "");
  writeFileSync(join(dir, "ext", "logic.test.mjs"), "");
  writeFileSync(join(dir, "ext", "nested", "helper.js"), "");
  writeFileSync(join(dir, "ext", "nested", "notes.md"), "");
  writeFileSync(join(dir, "ext", "node_modules", "dep.js"), "");
  writeFileSync(join(dir, "ext", ".hidden", "secret.mjs"), "");
  symlinkSync(join(dir, "ext", "extension.mjs"), join(dir, "ext", "linked.mjs"));
  const found = listFiles(join(dir, "ext"), isCodeFile).sort();
  assert.deepEqual(found, [join(dir, "ext", "extension.mjs"), join(dir, "ext", "nested", "helper.js")]);
  assert.equal(isCodeFile("x.cjs"), true);
  assert.equal(isCodeFile("done.test.mjs"), false);
});

function fakeSession({ isRemote = false, idle = true } = {}) {
  const calls = [];
  const logs = [];
  const rpc = {
    metadata: {
      snapshot: async () => ({ isRemote, workspacePath: isRemote ? null : "/session" }),
      isProcessing: async () => ({ processing: !idle }),
      activity: async () => ({ hasActiveWork: false }),
    },
    permissions: { pendingRequests: async () => ({ items: [] }) },
    tasks: { list: async () => ({ tasks: [] }) },
    instructions: {
      getSources: async () => {
        calls.push("getSources");
        return { sources: [] };
      },
      reload: async () => calls.push("instructions.reload"),
    },
    skills: { reload: async () => calls.push("skills.reload") },
    extensions: { reload: async () => calls.push("extensions.reload") },
  };
  return { rpc, calls, logs, log: (message, opts) => logs.push({ message, ...opts }) };
}

test("a remote session starts no timer and never reloads", async (t) => {
  const dir = tempDir(t);
  const timers = [];
  const ext = createRefreshExtension({
    pluginRoot: join(dir, "plugin"),
    copilotHome: join(dir, "copilot"),
    setTimer: (fn, ms) => timers.push({ fn, ms }),
  });
  const session = fakeSession({ isRemote: true });
  assert.equal(await ext.start(session), null);
  ext.onEvent({ type: "session.idle" });
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(timers, []);
  assert.deepEqual(session.calls, []);
});

test("a local session watches files, starts a timer and reloads on idle", async (t) => {
  const dir = tempDir(t);
  const pluginRoot = join(dir, "plugin");
  const copilotHome = join(dir, "copilot");
  mkdirSync(join(pluginRoot, "skills", "done"), { recursive: true });
  writeFileSync(join(pluginRoot, "skills", "done", "SKILL.md"), "v1");
  const timers = [];
  let clock = 0;
  const ext = createRefreshExtension({
    pluginRoot,
    copilotHome,
    setTimer: (fn, ms) => timers.push({ fn, ms }),
    now: () => clock,
  });
  const session = fakeSession();
  assert.ok(await ext.start(session));
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 3000);
  writeFileSync(join(pluginRoot, "skills", "done", "SKILL.md"), "v2");
  ext.onEvent({ type: "session.idle" });
  await new Promise((r) => setTimeout(r, 10));
  clock = 3000;
  ext.onEvent({ type: "session.idle", agentId: "child" });
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(session.calls, ["getSources"]);
  timers[0].fn();
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(session.calls, ["getSources", "skills.reload"]);
  assert.match(session.logs[0].message, /refreshing skills in place/);
  assert.equal(session.logs[0].level, "info");
});

test("idle requires no processing, work, pending requests or running subagents", async () => {
  const base = () => ({
    metadata: {
      isProcessing: async () => ({ processing: false }),
      activity: async () => ({ hasActiveWork: false }),
    },
    permissions: { pendingRequests: async () => ({ items: [] }) },
    tasks: { list: async () => ({ tasks: [{ type: "agent", status: "completed" }, { type: "shell", status: "running" }] }) },
  });
  assert.equal(await sessionIsIdle(base()), true);
  const busy = base();
  busy.metadata.isProcessing = async () => ({ processing: true });
  assert.equal(await sessionIsIdle(busy), false);
  const working = base();
  working.metadata.activity = async () => ({ hasActiveWork: true });
  assert.equal(await sessionIsIdle(working), false);
  const asking = base();
  asking.permissions.pendingRequests = async () => ({ items: [{}] });
  assert.equal(await sessionIsIdle(asking), false);
  const agent = base();
  agent.tasks.list = async () => ({ tasks: [{ type: "agent", status: "running" }] });
  assert.equal(await sessionIsIdle(agent), false);
});

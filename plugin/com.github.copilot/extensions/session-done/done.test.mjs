import { test } from "node:test";
import assert from "node:assert/strict";
import { createDoneExtension, doneName, isDoneInvocation } from "./done.mjs";

function fakeSession({
  title = "Some work",
  isRemote = false,
  workspacePath = "/session",
  queued = true,
  setBehavior = "save",
} = {}) {
  const calls = [];
  const errors = [];
  let name = title;
  const session = {
    rpc: {
      metadata: { snapshot: async () => ({ isRemote, workspacePath }) },
      name: {
        get: async () => ({ name }),
        set: async ({ name: next }) => {
          calls.push(["rename", next]);
          if (setBehavior === "throw") throw new Error("Cannot save");
          if (setBehavior === "save") name = next;
        },
      },
      commands: {
        enqueue: async ({ command }) => {
          calls.push(["enqueue", command]);
          return { queued };
        },
      },
    },
    log: (message, options) => {
      if (options?.level === "error") errors.push(message);
    },
  };
  return { session, calls, errors };
}

function setup(options = {}) {
  const fake = fakeSession(options);
  const ext = createDoneExtension(() => fake.session);
  return { ...fake, ext };
}

const invocation = (data = {}) => ({
  type: "skill.invoked",
  data: { name: "done", pluginName: "digits", trigger: "user-invoked", ...data },
});

async function run(ext, data) {
  await ext.onEvent(invocation(data));
  await ext.onEvent({ type: "user.message", data: { content: "context", source: "memory" } });
  await ext.onEvent({ type: "user.message", data: { content: "/digits:done" } });
}

async function complete(ext) {
  await ext.onEvent({ type: "assistant.message", data: { content: "- Fixed the parser and ran its tests.\n" } });
  await ext.onEvent({ type: "session.idle", data: {} });
}

test("recap, then rename, then reset", async () => {
  const f = setup({ title: "PROJ-123: fix [parser]; $HOME" });
  await run(f.ext);
  assert.deepEqual(f.calls, []);
  await complete(f.ext);
  assert.deepEqual(f.calls, [
    ["rename", "[DONE] PROJ-123: fix [parser]; $HOME"],
    ["enqueue", "/new"],
  ]);
  assert.deepEqual(f.errors, []);
});

test("an existing [DONE] prefix is not doubled", async () => {
  const f = setup({ title: "[DONE] Fix an export" });
  await run(f.ext);
  await complete(f.ext);
  assert.deepEqual(f.calls, [["enqueue", "/new"]]);
  assert.deepEqual(f.errors, []);
});

test("an unnamed session becomes Untitled session", async () => {
  const f = setup({ title: null });
  await run(f.ext);
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Untitled session"], ["enqueue", "/new"]]);
});

test("titles are normalized", async () => {
  const cases = [
    ["Fix\nan\t\u0085export", "[DONE] Fix an export"],
    ['Fix "export"', "[DONE] Fix 'export'"],
    ["[DONE] Fix\u0000\u007fan export", "[DONE] Fix an export"],
    ["\u0000\u0001\u007f\u009f", "[DONE] Untitled session"],
    ["   ", "[DONE] Untitled session"],
  ];
  for (const [title, expected] of cases) {
    const f = setup({ title });
    await run(f.ext);
    await complete(f.ext);
    assert.deepEqual(f.calls, [["rename", expected], ["enqueue", "/new"]], title);
    assert.deepEqual(f.errors, []);
  }
});

test("long titles keep at most 93 units without splitting a code point", async () => {
  const title = "x".repeat(92) + "\u{1F680}".repeat(8);
  const f = setup({ title });
  await run(f.ext);
  await complete(f.ext);
  const renamed = f.calls[0][1];
  assert.equal(renamed, "[DONE] " + "x".repeat(92));
  assert.ok(renamed.length <= 100);
  assert.deepEqual(f.calls[1], ["enqueue", "/new"]);
  const even = doneName("y".repeat(91) + "\u{1F680}".repeat(8));
  assert.equal(even, "[DONE] " + "y".repeat(91) + "\u{1F680}");
  assert.equal(even.length, 100);
});

test("remote, unsaved sessions and arguments are refused", async () => {
  for (const [options, data] of [
    [{ isRemote: true }, {}],
    [{ workspacePath: null }, {}],
    [{}, { arguments: "finish something else" }],
  ]) {
    const f = setup(options);
    await run(f.ext, data);
    await complete(f.ext);
    assert.deepEqual(f.calls, []);
    assert.equal(f.errors.length, 1);
  }
});

test("blank arguments are accepted", async () => {
  const f = setup();
  await run(f.ext, { arguments: "   " });
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"], ["enqueue", "/new"]]);
});

test("only a user invocation of this plugin's skill starts the flow", async () => {
  for (const data of [
    { trigger: "agent-invoked" },
    { trigger: "context-load" },
    { pluginName: "other" },
    { name: "investigate" },
  ]) {
    const f = setup();
    await run(f.ext, data);
    await complete(f.ext);
    assert.deepEqual(f.calls, []);
    assert.deepEqual(f.errors, []);
  }
  for (const extra of [{ agentId: "child" }, { checkpoint: { id: 1 } }]) {
    const f = setup();
    await f.ext.onEvent({ ...invocation(), ...extra });
    await f.ext.onEvent({ type: "user.message", data: { content: "/digits:done" } });
    await complete(f.ext);
    assert.deepEqual(f.calls, []);
  }
  const f = setup();
  await f.ext.onEvent({ type: "skill.invoked", data: { name: "digits:done", trigger: "user-invoked" } });
  await f.ext.onEvent({ type: "user.message", data: { content: "/digits:done" } });
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"], ["enqueue", "/new"]]);
  assert.equal(isDoneInvocation({ type: "skill.invoked" }), false);
});

test("a failing rename does not reset", async () => {
  const f = setup({ setBehavior: "throw" });
  await run(f.ext);
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"]]);
  assert.match(f.errors[0], /Cannot save/);
});

test("an unpersisted rename does not reset", async () => {
  const f = setup({ setBehavior: "ignore" });
  await run(f.ext);
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"]]);
  assert.match(f.errors[0], /could not be verified/);
});

test("a refused queue keeps the marker and asks for /new", async () => {
  const f = setup({ queued: false });
  await run(f.ext);
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"], ["enqueue", "/new"]]);
  assert.match(f.errors[0], /Marked \[DONE\].*Run \/new/);
});

test("a repeated invocation is a no-op", async () => {
  const f = setup();
  await f.ext.onEvent(invocation());
  await f.ext.onEvent(invocation());
  await f.ext.onEvent({ type: "user.message", data: { content: "/digits:done" } });
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"], ["enqueue", "/new"]]);
  assert.deepEqual(f.errors, []);
});

test("abort, errors and new human input cancel; a later run still works", async () => {
  for (const cancel of [
    { type: "abort", data: {} },
    { type: "session.error", data: { message: "boom" } },
    { type: "user.message", data: { content: "actually wait", source: "user" } },
  ]) {
    const f = setup();
    await run(f.ext);
    await f.ext.onEvent(cancel);
    await complete(f.ext);
    assert.deepEqual(f.calls, [], cancel.type);
    assert.deepEqual(f.errors, []);
    await run(f.ext);
    await complete(f.ext);
    assert.deepEqual(f.calls, [["rename", "[DONE] Some work"], ["enqueue", "/new"]]);
  }
});

test("a subagent reply is not a recap", async () => {
  const f = setup();
  await run(f.ext);
  await f.ext.onEvent({ type: "assistant.message", agentId: "child", data: { content: "sub reply" } });
  await f.ext.onEvent({ type: "session.idle", data: {} });
  assert.deepEqual(f.calls, []);
  assert.match(f.errors[0], /No final recap was saved/);
});

test("idle before the invocation's own user message keeps the request pending", async () => {
  const f = setup();
  await f.ext.onEvent(invocation());
  await f.ext.onEvent({ type: "assistant.message", data: { content: "early" } });
  await f.ext.onEvent({ type: "session.idle", data: {} });
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.errors, []);
  await f.ext.onEvent({ type: "user.message", data: { content: "/digits:done" } });
  await complete(f.ext);
  assert.deepEqual(f.calls, [["rename", "[DONE] Some work"], ["enqueue", "/new"]]);
});

test("the latest assistant message wins and an empty one leaves no recap", async () => {
  const f = setup();
  await run(f.ext);
  await f.ext.onEvent({ type: "assistant.message", data: { content: "- Real recap" } });
  await f.ext.onEvent({ type: "assistant.message", data: {} });
  await f.ext.onEvent({ type: "session.idle", data: {} });
  assert.deepEqual(f.calls, []);
  assert.match(f.errors[0], /No final recap was saved/);
});

test("no session means nothing is logged or called", async () => {
  const ext = createDoneExtension(() => undefined);
  await ext.onEvent(invocation());
  await ext.onEvent({ type: "user.message", data: {} });
  await ext.onEvent({ type: "session.idle", data: {} });
});

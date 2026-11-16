import assert from "node:assert/strict";
import { test } from "node:test";
import { DashboardState } from "./state.mjs";

const at = (seconds) => new Date(seconds * 1000).toISOString();
const ev = (type, seconds, data = {}, extra = {}) => ({
  type,
  ...(seconds === undefined ? {} : { timestamp: at(seconds) }),
  data,
  ...extra,
});
const child = (type, seconds, data = {}) => ev(type, seconds, data, { agentId: "child-1" });

function run(seconds = 100) {
  const state = new DashboardState();
  state.accept(ev("user.message", seconds));
  return state;
}

function expect(state, label, since, took) {
  assert.equal(state.label, label);
  if (arguments.length > 2) assert.equal(state.since, since);
  if (arguments.length > 3) assert.equal(state.took, took);
}

test("1: basic lifecycle and activity setters", () => {
  const state = new DashboardState();
  expect(state, "READY", undefined);
  state.accept(ev("user.message", 100));
  state.accept(ev("assistant.turn_end", 101));
  expect(state, "WORKING");
  state.accept(ev("session.idle", 102));
  expect(state, "YOUR TURN");
  state.setActivity(true);
  expect(state, "WORKING");
  state.setActivity(false);
  expect(state, "YOUR TURN");
});

test("2: pending requests are keyed per kind", () => {
  const state = run();
  state.accept(ev("permission.requested", 101, { requestId: "one" }));
  state.accept(ev("elicitation.requested", 102, { requestId: "one" }));
  state.accept(ev("permission.completed", 103, { requestId: "one" }));
  state.setActivity(true);
  expect(state, "NEEDS YOU");
  state.accept(ev("elicitation.completed", 104, { requestId: "one" }));
  expect(state, "WORKING");
});

test("3: requests resolved by a hook are ignored", () => {
  const state = new DashboardState();
  state.accept(ev("permission.requested", 100, { requestId: "x", resolvedByHook: true }));
  expect(state, "READY");
});

test("4: child events cannot finish the parent turn but can ask for input", () => {
  const state = run();
  state.accept(child("session.idle", 101));
  expect(state, "WORKING");
  state.accept(child("user_input.requested", 102, { requestId: "q" }));
  expect(state, "NEEDS YOU");
  state.accept(child("user_input.completed", 103, { requestId: "q" }));
  expect(state, "WORKING");
});

test("5: sync subagent spawned by a task tool", () => {
  const state = run();
  state.accept(ev("tool.execution_start", 101, { toolCallId: "spawn", toolName: "task" }));
  state.accept(child("subagent.started", 102, { toolCallId: "spawn", executionMode: "sync" }));
  expect(state, "SUBAGENTS", 100);
  state.accept(ev("tool.execution_start", 103, { toolCallId: "b", toolName: "bash" }));
  expect(state, "WORKING");
  state.accept(ev("tool.execution_complete", 104, { toolCallId: "b", success: true }));
  expect(state, "SUBAGENTS");
  state.accept(child("subagent.completed", 105, { toolCallId: "spawn" }));
  expect(state, "WORKING");
  state.accept(ev("tool.execution_complete", 106, { toolCallId: "spawn" }));
  state.accept(ev("assistant.turn_start", 107));
  expect(state, "WORKING", 100);
  state.accept(ev("session.idle", 110));
  expect(state, "YOUR TURN", 110);
});

test("6: background subagents while the parent idles", () => {
  const state = run();
  state.accept(ev("subagent.started", 101, { toolCallId: "a", executionMode: "background" }));
  state.accept(ev("subagent.started", 101, { toolCallId: "b", executionMode: "background" }));
  expect(state, "WORKING");
  state.accept(ev("assistant.turn_end", 102));
  expect(state, "WORKING");
  state.accept(child("assistant.idle", 102));
  expect(state, "WORKING");
  state.accept(ev("assistant.idle", 103));
  expect(state, "SUBAGENTS");
  state.accept(ev("assistant.turn_start", 104));
  expect(state, "WORKING", 100);
  state.accept(ev("assistant.idle", 105));
  state.accept(ev("subagent.completed", 105, { toolCallId: "a" }));
  expect(state, "SUBAGENTS");
  state.accept(ev("subagent.failed", 106, { toolCallId: "b" }));
  expect(state, "WORKING");
  state.setActivity(false, 107);
  expect(state, "YOUR TURN", 107);
});

test("7: explicit read_agent waits count as waiting on subagents", () => {
  const state = run();
  state.setTasks([{ type: "agent", status: "running", toolCallId: "bg", executionMode: "background" }], 100);
  state.accept(ev("tool.execution_start", 101, { toolCallId: "r1", toolName: "read_agent", arguments: { wait: false } }));
  expect(state, "WORKING");
  state.accept(ev("tool.execution_complete", 102, { toolCallId: "r1" }));
  state.accept(ev("tool.execution_start", 103, { toolCallId: "r2", toolName: "read_agent", arguments: { wait: true } }));
  expect(state, "SUBAGENTS");
  state.accept(child("permission.requested", 104, { requestId: "p" }));
  expect(state, "NEEDS YOU");
  state.accept(child("permission.completed", 105, { requestId: "p" }));
  expect(state, "SUBAGENTS");
  state.accept(ev("tool.execution_complete", 106, { toolCallId: "r2" }));
  expect(state, "WORKING");
  state.accept(ev("session.error", 107));
  expect(state, "ERROR");
});

test("8: task snapshots replace stale agents and ignore non-running tasks", () => {
  const state = run();
  state.accept(ev("subagent.started", 101, { toolCallId: "stale", executionMode: "background" }));
  state.setProcessing(false);
  state.setTasks([{ type: "agent", status: "running", toolCallId: "other", executionMode: "background" }], 102);
  expect(state, "SUBAGENTS");
  state.setTasks(
    [
      ...["completed", "idle", "cancelled", "failed"].map((status, i) => ({
        type: "agent",
        status,
        toolCallId: `t${i}`,
        executionMode: "background",
      })),
      { type: "shell", status: "running" },
      { type: "client", status: "running" },
    ],
    103,
  );
  expect(state, "WORKING");
  state.setActivity(false, null);
  expect(state, "YOUR TURN", undefined);
});

test("9: failed tools are not errors; session errors persist until a new message", () => {
  const state = run();
  state.accept(ev("tool.execution_start", 101, { toolCallId: "t", toolName: "bash" }));
  state.accept(ev("tool.execution_complete", 102, { toolCallId: "t", success: false }));
  expect(state, "WORKING");
  state.accept(ev("session.error", 103));
  state.accept(ev("session.idle", 104));
  expect(state, "ERROR");
  state.accept(ev("user.message", 105));
  expect(state, "WORKING");
});

test("10: abort clears pending input", () => {
  const state = run();
  state.accept(ev("permission.requested", 101, { requestId: "p" }));
  state.accept(ev("abort", 102));
  expect(state, "YOUR TURN");
  state.accept(ev("user.message", 103));
  expect(state, "WORKING");
});

test("11: run start survives steering, input and child idles", () => {
  const state = run(100);
  state.accept(ev("assistant.turn_start", 102));
  state.accept(ev("assistant.turn_end", 110));
  state.accept(ev("user.message", 112, { delivery: "steering" }));
  state.accept(ev("assistant.turn_start", 114));
  expect(state, "WORKING", 100);
  state.accept(ev("permission.requested", 120, { requestId: "p" }));
  expect(state, "NEEDS YOU", undefined);
  state.accept(ev("permission.completed", 150, { requestId: "p" }));
  expect(state, "WORKING", 100);
  state.accept(child("session.idle", 160));
  expect(state, "WORKING", 100);
  state.accept(ev("session.idle", 180));
  expect(state, "YOUR TURN", 180);
  state.setActivity(false, 200);
  state.accept(ev("session.idle", 210));
  expect(state, "YOUR TURN", 180);
  state.accept(ev("user.message", 300));
  expect(state, "WORKING", 300);
});

test("12: idle and queued deliveries start a new run", () => {
  const state = new DashboardState();
  state.accept(ev("user.message", 100, { delivery: "idle" }));
  state.accept(ev("assistant.turn_start", 102));
  state.accept(ev("user.message", 200, { delivery: "queued" }));
  state.accept(ev("assistant.turn_start", 202));
  state.setActivity(true, null);
  expect(state, "WORKING", 200);
  state.setActivity(false, null);
  expect(state, "YOUR TURN", undefined);
});

test("13: resumed activity keeps the original start", () => {
  const state = run(100);
  state.accept(ev("session.idle", 200));
  state.setActivity(true, 205);
  expect(state, "WORKING", 100);
  state.setActivity(false, 300);
  expect(state, "YOUR TURN", 300);
});

test("14: settling after input and after abort", () => {
  const state = run(100);
  state.accept(ev("user_input.requested", 120, { requestId: "u" }));
  state.accept(ev("session.idle", 150));
  expect(state, "NEEDS YOU");
  state.accept(ev("user_input.completed", 170, { requestId: "u" }));
  expect(state, "YOUR TURN", 170);
  state.accept(ev("user.message", 200));
  state.accept(ev("session.error", 210));
  expect(state, "ERROR", undefined);
  state.accept(ev("abort", 220));
  expect(state, "YOUR TURN", 220);
});

test("15: invalid timestamps throw a TypeError", () => {
  const state = new DashboardState();
  assert.throws(
    () => state.accept({ type: "user.message", timestamp: "not-a-timestamp", data: {} }),
    (error) => error instanceof TypeError && /Invalid dashboard event timestamp/.test(error.message),
  );
  expect(state, "READY");
});

const shell = (status = "running", attachmentMode = "attached") => ({
  type: "shell",
  status,
  attachmentMode,
});

test("16: attached shells give WATCHING", () => {
  const state = run(100);
  state.setTasks([shell(), shell()], 110);
  expect(state, "WORKING");
  state.accept(ev("assistant.idle", 120));
  expect(state, "WATCHING", 100);
  state.accept(ev("assistant.turn_start", 130));
  expect(state, "WORKING");
  state.accept(ev("session.idle", 140));
  expect(state, "WATCHING");
  state.setTasks([shell()], 150);
  expect(state, "WATCHING");
  state.setTasks([shell("completed")], 160);
  expect(state, "YOUR TURN", 160);
  state.setTasks([], 170);
  expect(state, "YOUR TURN", 160);
});

test("17: watching an idle parent with input, errors and detached shells", () => {
  const state = run(100);
  state.accept(ev("session.idle", 110));
  state.setTasks([shell()], 111);
  expect(state, "WATCHING");
  state.accept(ev("permission.requested", 120, { requestId: "p" }));
  expect(state, "NEEDS YOU");
  state.accept(ev("permission.completed", 121, { requestId: "p" }));
  expect(state, "WATCHING");
  state.accept(ev("session.error", 130));
  expect(state, "ERROR");
  state.accept(ev("abort", 140));
  expect(state, "WATCHING");
  state.setTasks(
    [shell("running", "detached"), shell("completed"), shell("cancelled"), shell("failed"), shell("idle")],
    160,
  );
  expect(state, "YOUR TURN", 160);
});

test("18: snapshot-style updates with unknown times", () => {
  const state = run(100);
  state.setActivity(false, null);
  state.setProcessing(false);
  state.setTasks([shell()], null);
  expect(state, "WATCHING", 100);
  state.setTasks([], null);
  expect(state, "YOUR TURN", undefined);
});

test("19: took measures the finished run", () => {
  const state = run(100);
  state.accept(ev("user.message", 150, { delivery: "steering" }));
  assert.equal(state.took, undefined);
  state.accept(ev("session.idle", 352));
  expect(state, "YOUR TURN", 352, 252);
  state.accept(ev("assistant.turn_start", 400));
  state.accept(ev("session.idle", 405));
  expect(state, "YOUR TURN", 405, 5);
  state.accept(ev("user.message", 500));
  state.setActivity(false, null);
  expect(state, "YOUR TURN", undefined, undefined);
});

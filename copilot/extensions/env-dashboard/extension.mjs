// Copilot CLI extension that publishes this chat's activity to tmux pane
// options, which the ai-agents dashboard renders. See state.mjs for the
// activity rules; this module only handles the SDK and tmux transport.

import { execFileSync } from "node:child_process";
import { joinSession } from "@github/copilot-sdk/extension";
import { DashboardState } from "./state.mjs";

const TMUX_TIMEOUT_MS = 2000;
const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 30000;

const PANE = process.env.TMUX_PANE ?? "";
const SOCKET = socketPath(process.env.TMUX ?? "");
const ENABLED = SOCKET !== "" && /^%\d+$/.test(PANE);
const PID = String(process.pid);

let state = new DashboardState();
let buffer = [];
let initializing = true;
let revision = 0;
let lastKey;
let lastFolder;
let trackingFailed = false;
let syncing;
let retryTimer;
let retryDelay = FIRST_RETRY_MS;
let session;

function socketPath(value) {
  const fields = value.split(",");
  return fields.slice(0, -2).join(",");
}

function describe(error) {
  return error instanceof Error ? error.message : String(error);
}

function tmux(...commands) {
  const args = ["-S", SOCKET];
  commands.forEach((command, index) => {
    if (index > 0) args.push(";");
    args.push(...command);
  });
  return String(
    execFileSync("tmux", args, {
      encoding: "utf8",
      timeout: TMUX_TIMEOUT_MS,
      stdio: ["ignore", "pipe", "pipe"],
    }),
  ).trim();
}

function setPane(option, value) {
  return ["set-option", "-p", "-t", PANE, option, value];
}

function render(value) {
  return value === undefined || value === null ? "" : String(value);
}

function publishState() {
  if (!ENABLED) return;
  const label = trackingFailed ? "UNKNOWN" : state.label;
  const since = trackingFailed ? "" : render(state.since);
  const took = trackingFailed ? "" : render(state.took);
  const key = [label, since, took].join("|");
  if (key === lastKey) return;
  tmux(
    setPane("@env-dashboard-owner", PID),
    setPane("@env-copilot-state", label),
    setPane("@env-copilot-since", since),
    setPane("@env-copilot-took", took),
    ["refresh-client", "-S"],
  );
  lastKey = key;
}

async function publishFolder() {
  if (!ENABLED) return;
  try {
    const snapshot = await session.rpc.metadata.snapshot();
    const path = snapshot?.workspacePath;
    const folder = !snapshot?.isRemote && typeof path === "string" && path !== "" ? path : "";
    if (folder === lastFolder) return;
    if (folder) {
      tmux(setPane("@env-session-dir", folder));
    } else {
      tmux(["set-option", "-p", "-u", "-t", PANE, "@env-session-dir"]);
    }
    lastFolder = folder;
  } catch (error) {
    console.error(
      `Environment dashboard: could not publish the session folder: ${describe(error)}`,
    );
  }
}

function cancelRetry() {
  if (retryTimer !== undefined) {
    clearTimeout(retryTimer);
    retryTimer = undefined;
  }
}

function report(error) {
  trackingFailed = true;
  console.error(`Environment dashboard update failed: ${describe(error)}`);
  try {
    publishState();
  } catch (publishError) {
    console.error(
      `Environment dashboard: could not display UNKNOWN: ${describe(publishError)}`,
    );
  }
  if (session && ENABLED && retryTimer === undefined) {
    retryTimer = setTimeout(() => {
      retryTimer = undefined;
      void synchronise();
    }, retryDelay);
    retryTimer?.unref?.();
    retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS);
  }
}

async function runSynchronise() {
  try {
    initializing = true;
    const fresh = new DashboardState();
    const history = await session.getEvents();
    for (const event of history ?? []) fresh.accept(event);
    const metadata = session.rpc.metadata;
    const [activity, pending, processing, tasks] = await Promise.all([
      metadata.activity(),
      session.rpc.permissions.pendingRequests(),
      metadata.isProcessing(),
      session.rpc.tasks.list(),
    ]);
    fresh.setActivity(Boolean(activity?.hasActiveWork), null);
    fresh.setProcessing(Boolean(processing?.processing));
    fresh.setTasks(tasks?.tasks ?? [], null);
    for (const item of pending?.items ?? []) {
      fresh.accept({ type: "permission.requested", data: { requestId: item.requestId } });
    }
    const replay = buffer;
    buffer = [];
    for (const event of replay) fresh.accept(event);
    state = fresh;
    trackingFailed = false;
    publishState();
    initializing = false;
    cancelRetry();
    retryDelay = FIRST_RETRY_MS;
  } catch (error) {
    buffer = [];
    report(error);
    return;
  }
  await publishFolder();
}

function synchronise() {
  if (!syncing) {
    syncing = runSynchronise().finally(() => {
      syncing = undefined;
    });
  }
  return syncing;
}

async function reconcile() {
  const seen = revision;
  try {
    const metadata = session.rpc.metadata;
    const [activity, processing, tasks] = await Promise.all([
      metadata.activity(),
      metadata.isProcessing(),
      session.rpc.tasks.list(),
    ]);
    // An answer that predates a newer event must never finish that newer turn.
    if (seen !== revision || initializing || trackingFailed) return;
    state.setActivity(Boolean(activity?.hasActiveWork));
    state.setProcessing(Boolean(processing?.processing));
    state.setTasks(tasks?.tasks ?? []);
    publishState();
  } catch (error) {
    report(error);
  }
}

const SUBAGENT_EVENTS = new Set(["subagent.started", "subagent.completed", "subagent.failed"]);
const PARENT_RECONCILE_EVENTS = new Set([
  "session.idle",
  "assistant.idle",
  "abort",
  "session.background_tasks_changed",
]);

function onEvent(event) {
  if (!ENABLED) return;
  revision += 1;
  if (initializing || trackingFailed) {
    buffer.push(event);
    return;
  }
  try {
    state.accept(event);
    publishState();
  } catch (error) {
    report(error);
  }
  if (SUBAGENT_EVENTS.has(event.type) || (!event.agentId && PARENT_RECONCILE_EVENTS.has(event.type))) {
    void reconcile();
  }
}

function cleanup() {
  cancelRetry();
  try {
    const owner = tmux(["display-message", "-p", "-t", PANE, "#{@env-dashboard-owner}"]);
    if (owner !== PID) return;
    const unset = (option) => ["set-option", "-pu", "-t", PANE, option];
    tmux(
      unset("@env-copilot-state"),
      unset("@env-copilot-since"),
      unset("@env-copilot-took"),
      unset("@env-session-dir"),
      unset("@env-dashboard-owner"),
      ["refresh-client", "-S"],
    );
  } catch (error) {
    console.error(`Environment dashboard cleanup failed: ${describe(error)}`);
  }
}

try {
  session = await joinSession({ onEvent });
} catch (error) {
  report(error);
  throw error;
}

if (ENABLED) {
  process.once("exit", cleanup);
  process.once("SIGTERM", () => process.exit(0));
  process.once("SIGINT", () => process.exit(0));
  await synchronise();
}

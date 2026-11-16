// Pure activity state machine for the environment dashboard. No I/O.

const INPUT_KINDS = new Set([
  "elicitation",
  "exit_plan_mode",
  "permission",
  "auto_mode_switch",
  "user_input",
  "session_limits_exhausted",
]);

const IDLE = "YOUR TURN";

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function eventSeconds(event) {
  if (event.timestamp === undefined || event.timestamp === null) {
    return nowSeconds();
  }
  const milliseconds = new Date(event.timestamp).getTime();
  if (!Number.isFinite(milliseconds)) {
    throw new TypeError(
      `Invalid dashboard event timestamp: ${String(event.timestamp)}`,
    );
  }
  return Math.floor(milliseconds / 1000);
}

export class DashboardState {
  #working = false;
  #failed = false;
  #started = false;
  #pending = new Set();
  #processing = false;
  #shells = false;
  #agents = new Map();
  #tools = new Map();
  #startedAt = undefined;
  #doneAt = undefined;

  get label() {
    if (this.#pending.size > 0) return "NEEDS YOU";
    if (this.#failed) return "ERROR";
    if (
      this.#working &&
      this.#agents.size > 0 &&
      (!this.#processing || this.#onlyWaitingOnAgents())
    ) {
      return "SUBAGENTS";
    }
    if (this.#working && this.#shells && !this.#processing) return "WATCHING";
    if (this.#working) return "WORKING";
    if (this.#agents.size > 0) return "SUBAGENTS";
    if (this.#shells && !this.#processing) return "WATCHING";
    if (!this.#started) return "READY";
    return IDLE;
  }

  get since() {
    const label = this.label;
    if (label === "WORKING" || label === "SUBAGENTS" || label === "WATCHING") {
      return this.#startedAt;
    }
    if (label === IDLE) return this.#doneAt;
    return undefined;
  }

  get took() {
    if (this.label !== IDLE) return undefined;
    if (this.#doneAt === undefined || this.#startedAt === undefined) return undefined;
    return Math.max(0, this.#doneAt - this.#startedAt);
  }

  #onlyWaitingOnAgents() {
    if (this.#tools.size === 0) return false;
    for (const [id, isWait] of this.#tools) {
      if (!isWait && this.#agents.get(id) !== "sync") return false;
    }
    return true;
  }

  // Settling rule: a change into YOUR TURN records the operation's time.
  // `time` is a function so a (possibly throwing) time lookup runs only when needed.
  #settle(before, time) {
    if (before === IDLE || this.label !== IDLE) return;
    this.#doneAt = undefined;
    const seconds = time();
    this.#doneAt = seconds === null ? undefined : seconds;
  }

  #applyActivity(active, timestamp) {
    if (active) {
      if (this.#startedAt === undefined && timestamp !== null) {
        this.#startedAt = timestamp;
      }
      this.#doneAt = undefined;
    }
    this.#working = active;
    if (!active) this.#applyProcessing(false);
    if (active) this.#started = true;
  }

  #applyProcessing(processing) {
    this.#processing = processing;
    if (!processing) this.#tools.clear();
  }

  setActivity(active, timestamp = nowSeconds()) {
    const before = this.label;
    this.#applyActivity(Boolean(active), timestamp);
    this.#settle(before, () => timestamp);
  }

  setProcessing(processing) {
    const before = this.label;
    this.#applyProcessing(Boolean(processing));
    this.#settle(before, nowSeconds);
  }

  setTasks(tasks, timestamp = nowSeconds()) {
    const before = this.label;
    const agents = new Map();
    let shells = false;
    for (const task of tasks ?? []) {
      if (task.type === "agent" && task.status === "running") {
        agents.set(task.toolCallId, task.executionMode);
      }
      if (
        task.type === "shell" &&
        task.status === "running" &&
        task.attachmentMode === "attached"
      ) {
        shells = true;
      }
    }
    this.#agents = agents;
    this.#shells = shells;
    this.#settle(before, () => timestamp);
  }

  accept(event) {
    const type = String(event.type ?? "");
    const data = event.data ?? {};
    const [kind, action] = type.split(".");
    const before = this.label;
    let time = () => eventSeconds(event);

    if (INPUT_KINDS.has(kind) && data.requestId) {
      const key = `${kind}:${data.requestId}`;
      if (action === "requested" && !data.resolvedByHook) {
        this.#pending.add(key);
      } else if (action === "completed") {
        this.#pending.delete(key);
      }
    } else if (type === "subagent.started") {
      this.#agents.set(data.toolCallId, data.executionMode);
    } else if (type === "subagent.completed" || type === "subagent.failed") {
      this.#agents.delete(data.toolCallId);
    } else if (event.agentId) {
      // A child agent cannot start or finish the parent's turn.
    } else if (type === "user.message" || type === "assistant.turn_start") {
      const seconds = eventSeconds(event);
      time = () => seconds;
      const freshRun =
        !this.#working ||
        (type === "user.message" &&
          (data.delivery === "idle" || data.delivery === "queued"));
      if (freshRun) {
        this.#startedAt = seconds;
        this.#tools.clear();
      }
      this.#doneAt = undefined;
      this.#started = true;
      this.#working = true;
      this.#processing = true;
      this.#failed = false;
    } else if (type === "tool.execution_start") {
      this.#processing = true;
      const isWait =
        data.toolName === "read_agent" && data.arguments?.wait === true;
      this.#tools.set(data.toolCallId, isWait);
    } else if (type === "tool.execution_complete") {
      this.#tools.delete(data.toolCallId);
    } else if (type === "assistant.idle") {
      this.#applyProcessing(false);
    } else if (type === "session.idle") {
      const seconds = eventSeconds(event);
      time = () => seconds;
      this.#applyActivity(false, seconds);
      if (data.aborted) this.#pending.clear();
    } else if (type === "session.error") {
      this.#started = true;
      this.#working = false;
      this.#applyProcessing(false);
      this.#failed = true;
      this.#doneAt = undefined;
    } else if (type === "abort") {
      const seconds = eventSeconds(event);
      time = () => seconds;
      this.#applyActivity(false, seconds);
      this.#failed = false;
      this.#pending.clear();
    }

    this.#settle(before, time);
  }
}

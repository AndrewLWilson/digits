// SDK-free logic for the session-done extension: after the /digits:done recap,
// mark the session title with [DONE] and queue the native /new command.

const DONE_PREFIX = "[DONE]";
const MAX_KEPT_UNITS = 93;
const FALLBACK_TITLE = "Untitled session";

export function isDoneInvocation(event) {
  if (!event || event.type !== "skill.invoked") return false;
  if (event.agentId || event.checkpoint) return false;
  const data = event.data ?? {};
  if (data.trigger !== "user-invoked") return false;
  return data.name === "digits:done" || (data.name === "done" && data.pluginName === "digits");
}

export function normalizeTitle(name) {
  if (name === null || name === undefined) return FALLBACK_TITLE;
  const cleaned = String(name)
    .replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ")
    .replace(/"/g, "'")
    .trim();
  return cleaned === "" ? FALLBACK_TITLE : cleaned;
}

export function doneName(rawName) {
  const title = normalizeTitle(rawName);
  if (title.startsWith(DONE_PREFIX)) return title;
  let kept = title.slice(0, MAX_KEPT_UNITS);
  const last = kept.charCodeAt(kept.length - 1);
  if (last >= 0xd800 && last <= 0xdbff) kept = kept.slice(0, -1);
  return `${DONE_PREFIX} ${kept}`;
}

const messageOf = (error) => (error && typeof error.message === "string" ? error.message : String(error));

export function createDoneExtension(getSession) {
  let pending = null;

  const report = (message) => {
    getSession()?.log(`Could not finish this chat: ${message}`, { level: "error" });
  };

  const release = (request) => {
    if (pending === request) pending = null;
  };

  async function start(event) {
    if (pending) return;
    const request = { started: false, recap: "", finishing: false };
    pending = request;
    try {
      const session = getSession();
      if (!session) throw new Error("the Copilot session is not available yet.");
      const args = event.data?.arguments ?? "";
      if (String(args).trim() !== "") {
        throw new Error("/digits:done takes no arguments; run /digits:done on its own.");
      }
      const snapshot = await session.rpc.metadata.snapshot();
      if (snapshot?.isRemote || !snapshot?.workspacePath) {
        throw new Error("a saved local session is required; remote or unsaved sessions cannot be marked done.");
      }
    } catch (error) {
      release(request);
      report(messageOf(error));
    }
  }

  async function finish() {
    const request = pending;
    if (!request || request.finishing) return;
    request.finishing = true;
    try {
      if (!request.started || request.recap === "") {
        throw new Error("No final recap was saved, so this chat stays open.");
      }
      const session = getSession();
      if (!session) throw new Error("the Copilot session is not available.");
      const before = (await session.rpc.name.get())?.name ?? null;
      const target = doneName(before);
      if (pending !== request) return;
      if (before !== target) await session.rpc.name.set({ name: target });
      const after = (await session.rpc.name.get())?.name ?? null;
      if (after !== target) {
        throw new Error(`the [DONE] title could not be verified (saved title: ${JSON.stringify(after)}).`);
      }
      if (pending !== request) return;
      const result = await session.rpc.commands.enqueue({ command: "/new" });
      if (!result?.queued) {
        throw new Error("Marked [DONE]; the new-session request was not accepted. Run /new yourself.");
      }
    } catch (error) {
      report(messageOf(error));
    } finally {
      release(request);
    }
  }

  return {
    onEvent(event) {
      if (isDoneInvocation(event)) return start(event);
      if (!pending || !event || event.agentId) return undefined;
      const data = event.data ?? {};
      switch (event.type) {
        case "abort":
        case "session.error":
          pending = null;
          return undefined;
        case "user.message":
          if (data.source !== undefined && data.source !== null && data.source !== "user") return undefined;
          if (pending.started) pending = null;
          else pending.started = true;
          return undefined;
        case "assistant.message":
          if (pending.started) pending.recap = typeof data.content === "string" ? data.content.trim() : "";
          return undefined;
        case "session.idle":
          if (pending.started) return finish();
          return undefined;
        default:
          return undefined;
      }
    },
  };
}

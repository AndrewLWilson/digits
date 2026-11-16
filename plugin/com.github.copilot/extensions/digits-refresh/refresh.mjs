// SDK-free logic for the digits-refresh extension. Imports only Node built-ins
// so `node --test` can exercise it without the Copilot CLI.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";

// Extensions must be reloaded last: that reload restarts this very process.
export const ORDER = ["instructions", "skills", "extensions"];

export const CHECK_INTERVAL_MS = 3000;

export function listFiles(root, accept) {
  const found = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
        walk(full);
      } else if (entry.isFile() && accept(entry.name)) {
        found.push(full);
      }
    }
  };
  walk(root);
  return found;
}

export function fingerprint(paths) {
  const hash = createHash("sha256");
  for (const path of [...new Set(paths)].sort()) {
    hash.update(path);
    hash.update("\0");
    let bytes;
    try {
      bytes = readFileSync(path);
    } catch {
      bytes = Buffer.from("<missing>");
    }
    hash.update(bytes);
    hash.update("\0");
  }
  return hash.digest("hex");
}

// groups: { <name>: { files: () => string[], reload: () => Promise } }
export function createRefresher({ groups, isIdle, notify, now = Date.now, settleMs = 3000 }) {
  const state = new Map();
  for (const name of ORDER) {
    const group = groups[name];
    if (!group) continue;
    state.set(name, { group, loaded: fingerprint(group.files()), pending: null, seenAt: 0 });
  }

  let inFlight = null;

  async function runCheck() {
    const time = now();
    for (const entry of state.values()) {
      const current = fingerprint(entry.group.files());
      if (current === entry.loaded) {
        entry.pending = null;
      } else if (current !== entry.pending) {
        entry.pending = current;
        entry.seenAt = time;
      }
    }

    const due = ORDER.filter((name) => {
      const entry = state.get(name);
      return entry !== undefined && entry.pending !== null && time - entry.seenAt >= settleMs;
    });
    if (due.length === 0 || !(await isIdle())) return [];

    // Mark as loaded before reloading so a failing reload is not retried in a loop.
    for (const name of due) {
      const entry = state.get(name);
      entry.loaded = entry.pending;
      entry.pending = null;
    }

    await notify(`Digits changed; refreshing ${due.join(", ")} in place for the next turn.`);

    const failures = [];
    for (const name of due) {
      try {
        await state.get(name).group.reload();
      } catch (error) {
        failures.push(`${name}: ${error?.message ?? String(error)}`);
      }
    }
    if (failures.length > 0) {
      await notify(
        `Digits could not finish refreshing (${failures.join("; ")}); use /restart once the chat is idle.`,
        "warning",
      );
    }
    return due;
  }

  return {
    check() {
      if (!inFlight) {
        inFlight = runCheck().finally(() => {
          inFlight = null;
        });
      }
      return inFlight;
    },
  };
}

const isSkillFile = (name) => name === "SKILL.md";
export const isCodeFile = (name) => /\.(mjs|cjs|js)$/.test(name) && !name.includes(".test.");

export function copilotHomeFrom(env = process.env, home = homedir()) {
  return env.COPILOT_HOME ? env.COPILOT_HOME : join(home, ".copilot");
}

export async function sessionIsIdle(rpc) {
  const [processing, activity, pending, tasks] = await Promise.all([
    rpc.metadata.isProcessing(),
    rpc.metadata.activity(),
    rpc.permissions.pendingRequests(),
    rpc.tasks.list(),
  ]);
  if (processing?.processing) return false;
  if (activity?.hasActiveWork) return false;
  if ((pending?.items ?? []).length > 0) return false;
  const running = (tasks?.tasks ?? []).some((t) => t?.type === "agent" && t?.status === "running");
  return !running;
}

export function buildGroups({ rpc, pluginRoot, copilotHome, userSources }) {
  return {
    instructions: {
      files: () => [join(copilotHome, "copilot-instructions.md"), ...userSources],
      reload: () => rpc.instructions.reload(),
    },
    skills: {
      files: () => [
        join(pluginRoot, "plugin.json"),
        ...listFiles(join(pluginRoot, "skills"), isSkillFile),
        ...listFiles(join(copilotHome, "skills"), isSkillFile),
      ],
      reload: () => rpc.skills.reload(),
    },
    extensions: {
      files: () => [
        ...listFiles(join(pluginRoot, "com.github.copilot", "extensions"), isCodeFile),
        ...listFiles(join(copilotHome, "extensions"), isCodeFile),
      ],
      reload: () => rpc.extensions.reload(),
    },
  };
}

const reportFailure = (error) => {
  console.error(`Digits refresh check failed: ${error?.message ?? String(error)}`);
};

// Wiring used by extension.mjs; kept here so it can be tested with fake sessions.
export function createRefreshExtension({
  pluginRoot,
  copilotHome,
  setTimer = setInterval,
  now = Date.now,
  settleMs = 3000,
  intervalMs = CHECK_INTERVAL_MS,
}) {
  let refresher = null;
  const trigger = () => {
    if (!refresher) return;
    try {
      refresher.check().catch(reportFailure);
    } catch (error) {
      reportFailure(error);
    }
  };

  return {
    onEvent(event) {
      if (event?.type === "session.idle" && !event.agentId) trigger();
    },
    async start(session) {
      const rpc = session.rpc;
      const snapshot = await rpc.metadata.snapshot();
      if (snapshot?.isRemote) return null;

      const sources = (await rpc.instructions.getSources())?.sources ?? [];
      const userSources = sources
        .filter((s) => s?.location === "user" && typeof s.sourcePath === "string" && isAbsolute(s.sourcePath))
        .map((s) => s.sourcePath);

      refresher = createRefresher({
        groups: buildGroups({ rpc, pluginRoot, copilotHome, userSources }),
        isIdle: () => sessionIsIdle(rpc),
        notify: (message, level = "info") => session.log(message, { level }),
        now,
        settleMs,
      });
      setTimer(trigger, intervalMs);
      return refresher;
    },
  };
}

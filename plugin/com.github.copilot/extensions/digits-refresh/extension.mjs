// Entry point for the digits-refresh extension. This is the only module that
// imports the Copilot CLI SDK; the logic lives in refresh.mjs.
import { joinSession } from "@github/copilot-sdk/extension";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { copilotHomeFrom, createRefreshExtension } from "./refresh.mjs";

const here = dirname(fileURLToPath(import.meta.url));
// extensions/<name> -> com.github.copilot -> plugin
const pluginRoot = resolve(here, "..", "..", "..");

const extension = createRefreshExtension({ pluginRoot, copilotHome: copilotHomeFrom() });

const session = await joinSession({
  onEvent(event) {
    extension.onEvent(event);
  },
});

try {
  await extension.start(session);
} catch (error) {
  console.error(`Digits refresh could not start: ${error?.message ?? String(error)}`);
}

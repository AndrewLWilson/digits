// Entry point for the session-done extension. This is the only module that
// imports the Copilot CLI SDK; the logic lives in done.mjs.
import { joinSession } from "@github/copilot-sdk/extension";
import { createDoneExtension } from "./done.mjs";

let session;
session = await joinSession(createDoneExtension(() => session));

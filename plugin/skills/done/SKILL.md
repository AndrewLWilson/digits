---
name: done
description: User-only command that wraps up this chat with a short recap, then the session-done extension saves a [DONE] marker on the session title and switches to a fresh session. Never call this skill on your own; only the user starts it with /digits:done.
user-invocable: true
disable-model-invocation: true
---

# Finish this chat

Usage: `/digits:done` (takes no arguments)

The user is closing out this chat. Your whole job is one final reply: a truthful
recap of what this chat actually achieved.

## The recap

- Write 2 to 4 short bullets, at most 120 words in total.
- Cover the results that matter, what was checked or tested to confirm them, and
  anything important that is still open or limited.
- Keep local changes apart from work that was pushed, merged, published or
  deployed. Do not claim success that was not verified.
- If no real work got done, say so plainly in one bullet.

## Rules

- Use only this conversation. Make no tool calls, do no further work, ask no
  questions and suggest no new tasks.
- Do not rename the session and do not open a new one yourself. After your reply
  is stored and the chat goes idle, the `session-done` extension prefixes the
  title with `[DONE]`, checks that the title was saved, and queues the native
  `/new` command. If that extension is not running, only the recap happens.

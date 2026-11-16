---
name: summarize
description: Read-only status recap of the current conversation (goals, progress, blocking questions, next steps) that changes nothing except saving the same recap in this session's workspace. Use for "where do things stand", "recap this chat", "status of this chat", or preparing a handoff to another chat.
user-invocable: true
---

# Summarize this chat

Usage: `/digits:summarize` (takes no arguments)

## Sources

Use this conversation, including any compaction summary, plus any plan or
handoff file that this same session keeps in its workspace. Nothing else.

## Stay read-only

- Do not post, edit, transition tickets, schedule anything or start new work.
- Do not re-run checks just to refresh status. Label time-sensitive facts with
  "as of" the moment they were last verified.

## Reply format

Four short sections, in this order:

1. **Goals**: the original request plus any scope changes the user made.
2. **Progress**: outcomes with their PR, ticket, run or file links. Say whether
   each one is local, pushed, merged, deployed or verified. Never report
   success that was not verified.
3. **Blocking questions**: one line per open decision or access need that only
   the user or a specific named person can resolve, with the available choices.
   Write "None" when there are none.
4. **Next steps**: an ordered list. Each step names who acts (the agent, the
   user, or a named team) and any approval it needs.

Keep it under roughly 250 words. When several independent workstreams exist,
group by workstream. Drop caveats that no longer apply. Link local files as
absolute `file:///` URLs.

## Save a copy

Write the identical recap to `files/summary.md` inside this session's workspace,
replacing any older copy. End the reply with a `file:///` link to that file and a
copy-pasteable command to view it rendered:

```bash
md-view '<absolute path of summary.md>'
```

If the session has no local workspace, or saving fails, say so and rely on the
inline recap.

---
name: challenge-pass
description: Run an investigation's conclusions past a fresh, read-only subagent before sharing them or naming a root cause. It tests each claim for direct observation, prior history, recent change, whole-population coverage, sourcing, a more direct signal, what labels really mean, independent confirmation, fit to the original goal, and internal consistency. Use before publishing analysis, asserting a root cause, or declaring something broken, benign, fixed, safe or harmless, and whenever asked to sanity-check or challenge an analysis.
user-invocable: true
---

# Challenge pass

Usage: `/digits:challenge-pass [claims or analysis text; default = current conclusions]`

## Why

Most well-founded objections surface from a handful of pointed questions that
compare a conclusion with evidence the agent has not yet looked at. Asking them
from a clean context keeps the review from anchoring on the first explanation
that seemed to fit.

## When to run

- before results leave the session for anywhere shared (chat, ticket, PR,
  incident);
- before naming a root cause;
- before recommending a production change, a new ticket, or doing nothing;
- before declaring anything missing, broken, harmless, benign, safe, fixed or
  self-healed.

Skip it for plain factual lookups and routine code edits.

## Steps

### 1. Build the claim sheet

Four parts:

- **Goal** - one or two lines naming the originating question, ticket or
  incident.
- **Claims** - numbered. Each lists its supporting evidence (the exact query,
  tool or source, what it returned, the time window) and the observation that
  would disprove it.
- **Already examined** - repositories, environments, windows, tickets, threads
  and sessions covered so far, so the challenger widens coverage instead of
  repeating it.
- **Pointers** - file paths, ticket keys, links, environment or tenant, window.

### 2. Launch the challenger

Start one subagent of type `general-purpose` (it needs lookup tools). Its
prompt is the complete text of `references/challenger-prompt.md` followed by
the claim sheet.

If the sheet has roughly nine or more claims, or spans several systems, split
the claims across two or three challengers running in parallel. Each one still
gets the full goal and context.

### 3. Check the challenger

Challenger findings can be confidently wrong. Re-check every finding that
would change a conclusion against the source it cites before accepting it.
Then put each claim in one class:

- **Holds** - no contrary evidence turned up, or new support turned up.
- **Changed** - corrected, narrowed or withdrawn, with the evidence.
- **Unverified** - blocked on access the agent lacks. Keep the read-only query
  (or the question to ask) that would settle it, and what each possible answer
  would mean.

### 4. Report first

Open with a short section titled "Challenge pass": what changed and why, what
remains unverified, and the questions or queries for the user. Rewrite changed
claims in the body of the analysis rather than adding footnotes. Only after
that may any post be drafted, under the normal approval rules.

If a change was caused by a recurring mistake, propose a lesson and route it
through `/digits:self-improve` or a harness edit the user approves.

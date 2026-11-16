# Reader-first reports and messages

Use when writing a standalone report, a chat or email message, a review, or a PR description, or when comparing numbers.
Scope: presentation and evidence backing only; approval to send stays with the skill that delivers to the destination.
Sources: maintainer agreements and the plugin's `request-review` skill.
Reviewed: 2026-11-16.
Recheck: the audience, the latest state, the population/window/unit behind any number, and real proof of publication or sending.

Decision procedure:

1. Lead with the result or the real blocker, then the change that matters and why.
2. Pick the matching canonical shape below; keep it short but not empty.
3. Make links absolute and clickable, attribute AI-drafted text, and draft locally until the destination is approved.

## Default

- Open with the outcome (or the genuine blocker), then the meaningful change and its reason. One or two short paragraphs is the norm; write more only for a requested plan or report or real complexity, not for routine caveats or unrequested checklists.
- Do not restate the request, narrate routine tool use, or re-explain a theory that has not changed. Say plainly what is unfinished or uncertain; add a next step only when one is actually needed.
- Give every open item or ticket key a short plain-language gloss, and do not lean on abbreviations coined earlier in the conversation. Tables use real field names, not invented symbols or footnote keys. Group long lists into a few logical clusters.
- Short is not the same as empty. A PR description covers what changes and why (design choices, changes made for reviewers, and accepted compromises, with links), how it was validated, and an example when users see the output. Keep it current; it is not a walk through the diff or a diary of abandoned plans.
- When you address review feedback, reply in each thread with the change and the commit so reviewers need not diff.
- Offer stylistic nits only when asked. Add short code comments only where the code is not self-evident.
- Attribution: any AI-drafted text posted on the user's behalf (for example chat messages, incident notes, shared documents, issue bodies and their comments, and PR reviews or comments) names the real tool and the verified model or mode. Leave out model detail you cannot verify, and include the user's name only when asked.
- Attribution format follows the destination. On GitHub, add a `<sub>…</sub>` line with a robot emoji noting that AI produced the text for the user and naming the tool and model. Where a tracker renders Markdown into rich text, put that sentence in italics as the opening line and avoid raw HTML entirely. The first time you post to a destination of a new kind, look at how it actually rendered. Having an attribution line does not mean you may post.
- Readers outside the conversation have not seen it: spell out what was asked, which boundary is relevant, what you concluded, and how far the evidence reaches and where it stops. Move audit detail to an appendix. Do not open with an unexplained verification section or include facts just because you collected them. Draft locally; publish only where approved.
- Tickets and PR descriptions aimed at whoever executes the work contain durable scope, rationale, safeguards, and that person's next step. Coordination logistics (how to upload, attachment status, what to click) go in the terminal handoff, not the lasting text.
- When you point at an artifact's path, say whether it is a broad inventory for review or a verified list of actions.

## Canonical output shapes

Blocked — say the work is ready but a named risk needs a named owner to check something before a gate opens; give the owner and the next action, and keep "handoff expected" separate from "receipt verified". Example:

> The migration PR is ready, but the backfill could double-count March rows. The data-platform owner needs to confirm the dedupe key before the Thursday deploy slot is released. Handoff is expected today; receipt is not yet verified.

Numbers that disagree — point out that the figures cover different scopes, such as a single thread against an entire billing day, and attach population, window with time zone, unit, and source to each before comparing. Totals per account per day, per user per day, and per thread must never be combined, and a rounded summary is not a precise ledger amount. Causation, correlation, absence from a source, and absence of evidence are four distinct claims. Example:

> The 412 is requests in one thread (UTC, 14:00–15:00, gateway log); the 9,870 is all requests for the account on 2026-11-12 (UTC, billing export). They measure different populations, so neither contradicts the other.

Standalone analysis — question, result, the causes and limits that matter, then the decision needed. Each chart answers one specific comparison; titles name the populations, axes give units and window. Once full results exist, replace earlier sample-based wording. Example:

> Question: did the retry change cut failed exports? Result: failures fell from 3.1% to 0.4% of 18,200 exports (Oct vs Nov, UTC). Limit: November had no quarter-end load. Decision: keep the change and recheck after quarter end?

Review request — use the existing `request-review` skill; it resolves reviewers, detects duplicates, gets approval of the exact text, sends, and handles any ticket transition. Recheck PR, head, and state at send time, and drop transient remarks (such as "tests not pushed yet") without fresh proof. Drafting is not sending. Example:

> Asking globex-reviewer to review PR 88 (head `a1b2c3d`, checks green as of 10:42 local): it adds export retries; please focus on the backoff limits.

Status update — reconcile earlier reports, decisions made in chat, and real source or runtime evidence through whichever status-update skill is in use; do not paste the shared context into it. Example:

> Since Monday: the retry fix merged (PR 88) and the November export completed with matching checksums. Still open: the data-platform owner's dedupe-key check.

PR description — a one-sentence TL;DR and a few concrete bullets, using this template:

```markdown
<sub>🤖 This text was AI-generated by <tool> (<model>) for <user>.</sub>

### [PROJ-123](https://example-org.example/browse/PROJ-123)

### Overview of Changes

> ⚡ **tl;dr** Export jobs now retry transient storage errors, so nightly deliveries stop failing on brief outages.

- Retries live in `export/retry.py` (`with_backoff`), capped at three attempts because the storage SLA recovers within a minute.
- Failure rate in the staging run fell from 3.1% to 0.4% of 18,200 exports.
- Alerting on exhausted retries is deliberately left for a follow-up PR.

Validated with the unit suite and one staging export; this PR is second in the stack and the alerting PR depends on it.
```

- The TL;DR has to stand on its own. Bullets cite files or symbols in backticks and state facts instead of touring the diff; they cover design decisions and reasons, real figures, linked plans, accepted compromises, and what is intentionally left for another PR (two to five bullets).
- The closing line states how it was validated and, for stacks, where this PR sits and what depends on it.
- Drop the ticket heading when no ticket is verified. The title follows Conventional Commits plus the repository's ticket and bump conventions; see [GitHub delivery](../workflows/github-delivery.md).

## Links and approval dialogs

- Write paths in absolute form. For a local file the reader is meant to click, give an explicit absolute `file:///` URL and percent-encode any reserved characters in it; inside commands, keep ordinary filesystem paths rather than URLs.
- If the user ought to open a local Markdown document such as a plan, report, handoff, or draft, and the viewer is available, pair its `file:///` link with an `md-view '/abs/path.md'` command (see [workspace and terminal](workspace-and-terminal.md)); the link remains the primary pointer. Anything taller than a single screen goes into a saved file instead of living only in the chat.
- When evidence hinges on them, construct genuine permalinks: to PRs and specific file lines, to workflow runs, and to issues or wiki pages.
- Slack treats a stray `<`, `>`, or `&` that is not part of an intended link or mention as markup, so rephrase placeholders like `v<N>`.
- For commands the user runs, target whatever shell the private tool binding names, defaulting to POSIX `sh`. Commands addressed to other people (in tickets, chat, docs, or PRs) stick to portable `bash`/`zsh` and, when practical, get one local trial run first, since BSD and GNU utilities behave differently, as do LibreSSL and OpenSSL.
- An approval prompt, in plain text, says precisely what will be done or sent, where it is going, what it will affect, and what it will not do — without tables, bold text, or code fences. If a structured user-input tool exists, use it rather than asking in free text.

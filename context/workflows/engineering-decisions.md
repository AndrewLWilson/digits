# Engineering decisions and evidence

Use when comparing designs, investigating a mechanism nobody is sure about, or stress-testing a consequential change (infrastructure, compatibility, capacity, and similar).
Scope: reasoning and source review only; following this page gives you no production access and no right to run anything.
Sources: agreements with the maintainer plus what reviewed incidents taught; nothing is borrowed from an outside procedure.
Reviewed: 2026-11-16.
Recheck: the actual source and runtime, how far the evidence reaches, dependencies, and approval.

Decision procedure:

1. Frame the outcome, constraints, and acceptance signal before touching an implementation.
2. Establish the mechanism with direct evidence and state what is still unproven.
3. Test any "blocked" or "done" claim against the stated goal.
4. For consequential changes, challenge the strongest assumptions before publishing.

## Frame the decision before choosing an implementation

- Write down the desired outcome, non-goals, constraints, current behaviour, and the
  signal that will count as acceptance. Identify producers and consumers, the owning
  layer, and any existing helper or contract. Keep verified facts, hypotheses, and
  unknowns visibly separate; never disguise an unknown as settled by sketching detailed
  architecture around it.
- Place the simplest workable option beside realistic alternatives, including "change
  nothing" when that is viable. Compare them on reversibility, failure modes,
  compatibility, cost and capacity, blast radius, and operational complexity. Explain why
  the chosen option fits and what evidence would reverse the choice. Avoid generic
  frameworks for a single consumer without proven need. When options differ materially in
  scope or behaviour, let the user decide; a polished recommendation is not approval.
- Long-lived contracts, and the reasons behind them, go in whatever place the repository
  already uses for design docs. What experiments found, which approvals are outstanding,
  and how far execution has got are tracked in the workstream instead. A brief note
  recording the decision is plenty; a fix does not need its own new document.

## Establish the mechanism, not just a plausible story

- Begin at the failing artifact and trace the callers, deployments, consumer paths, and
  configuration that matter. Compare when the behaviour started against a known-good state.
  Patterns from past incidents are hypotheses, not proof. Prefer direct signals over
  proxies: configuration reveals what someone intended, a live process reveals what was
  picked up, and only doing the real operation reveals whether it is accepted.
- Whenever a conclusion carries weight, record it in a compact table of three rows:
  1. **Claim** — limited to a stated population and period, and tied to the precise ref
     plus a rerunnable query, check, or artifact, along with its run time and output.
  2. **Why it implies the mechanism** — the direct causal path, alternatives considered,
     and contrary evidence.
  3. **Still unproven** — coverage gaps, uncertainty, and the observation that would
     refute the claim.
- Surprising or high-impact claims need a second independent signal where one exists;
  repeating the same source is not independence. A search with no results, a sample
  showing zero, or a source you could not reach is never evidence that something is
  absent. Say openly where results were capped or filtered, which fields were missing, and
  which populations went unseen, so incomplete evidence never quietly reads as an
  all-clear. When a conclusion changes, recompute its supporting rows instead of leaving
  stale numbers beside it. Before trusting a result, make sure the collection step
  actually worked and produced data of the shape you expected; output from a failed
  parser, a wrapped error, or an absent series must not be presented as "zero, healthy".
- Stay inside the approved access and cost envelope: draft heavy production queries for
  the user rather than running them, and never borrow another identity to fill a gap. See
  the [data warehouse page](../domains/data-warehouse.md) where relevant. Self-review by
  the engineer is not the independent human review high-stakes analyses need; see
  [Validate analyses separately](../domains/data-warehouse.md#validate-analyses-separately).

## Blockers, done, and approval conditions

- Before declaring something blocked, confirm (a) the refused or failing step is really
  required for the requested outcome and is not just an optional preflight, and (b) no
  access you already hold provides equivalent evidence, such as warehouse metadata,
  deploy manifests, Git history, or a read-only check that worked in an earlier session.
  Never propose an escalation the user has said is unavailable; mark the step skipped or
  unverified instead.
- Judge completion and approval against the stated goal and the most recent stakeholder
  decision. Label every concern as a blocker, a known pre-existing issue, or an optional
  follow-up. Previously deferred items and unrequested follow-ups (for example from an old
  plan) never block closure or approval; list them separately.

## Challenge consequential changes before publication

- Review depth follows risk rather than the number of changed lines. A tiny diff can
  warrant closer inspection than a sweeping mechanical one when it touches permissions
  (IAM), anything that destroys or retires resources, schema migrations, paths carrying
  sensitive data, contracts with external APIs, or how the code retries, times out,
  batches, or runs concurrently. Hunt for genuine defects and leave style alone.
- Ahead of publishing a design or PR like that, go after the assumptions it leans on
  hardest and every worry that was waved away ("there is only one caller", "that is
  already bounded", "the default is safe"). Factual statements beyond the diff are in
  scope too: descriptions, guides, and design docs that name artifacts, access, or restart
  and apply steps.
- Review bounded changes yourself. Bring in a separate read-only reviewer only when the
  independent context required is large; it is optional, not a ritual. Brief any reviewer
  with the goal, constraints, exact source or diff, claims, evidence, and pointed
  questions, and grant them no new access.
- Cover unhappy paths: invalid or missing configuration, partial failure, retries and
  restarts, cancellation, timeouts, double execution, legacy consumers, and disable or
  retire. For dependency or API changes, check the interface members you actually call,
  including generated methods and required attributes; permissive mocks can hide
  signature drift, so where practical exercise the real local interface in isolation
  while mocking or disabling external I/O.
- When someone asserts a limit, walk it up through the code that calls it and work out
  what it actually bounds: one request, one batch, one worker or pod, one tenant, or the
  entire fleet. Small caps grow quickly once fan-out, replica counts, retries, and
  schedules that overlap are multiplied in. Spell out the unit and scope before giving any
  figure for real load or memory, because a limit on a single run says nothing about the
  total across the fleet.
- Reproduce every reported problem against canonical source before accepting it; a valid
  concern can still suggest the wrong fix. Mark each material claim supported, revised, or
  unresolved, fix the real defects, and rerun whatever checks they touch. Go through the
  challenge again only if the change or the evidence has moved substantially, not until a
  reviewer runs out of comments.
- Before altering an alert, a threshold, or a schedule, replay the proposed rule against
  historical data covering both calm stretches and real incidents, wherever such data
  exists. Keep a genuinely sharper signal distinct from symptoms that are merely silenced.
  Rather than claiming nothing is missed, list the periods left untested and explain how
  the rule trades missed alerts against noisy ones.
- For target ownership, previews, rollout, and rollback limits, use
  [infrastructure lifecycle](infra-lifecycle.md); for exact-head checks, use
  [GitHub delivery](github-delivery.md). Close by stating what was decided, which
  conclusion shifted along the way, and the biggest risk that remains; a short answer can
  skip the evidence table and any formal review summary.

Example: a PR raises a per-batch limit from 100 to 500 rows. With 8 workers and 3 retries,
the effective fleet ceiling is far higher than "500"; state it in rows per tenant per run
before claiming the change is safe for the `acme` warehouse.

# Artifact shapes

How investigation outputs should look. Publishing any of them requires the
approval that applies to it; before that, show the exact text, the destination
and the identity it will be posted as.

## 1. Tickets (any tracker)

- Search for an existing ticket first. If one exists, propose a comment there
  instead of a new ticket and say why.
- Keep the description actionable: a short problem statement, then acceptance
  criteria. Put longer analysis and implementation ideas in a separate comment
  headed as recommendations.
- Link the change that introduced the problem, plus related incidents and
  duplicates.
- Describe impact concretely: the observed symptom, affected environments or
  tenants, how often it happens, and cost where it matters. Cover the whole
  blast radius, not just the place where it was first noticed.
- Required fields come from the bindings or context. Never guess custom field
  IDs. Read the created ticket back to confirm it.

## 2. Comments and posts (tickets, GitHub, chat, incidents)

- The first sentence carries whatever changes the reader's understanding: the
  answer, a correction, or a fact that contradicts what people believe now.
  Evidence follows.
- Analysis comments include evidence someone can re-run: queries, links, time
  windows.
- When drafting in the user's voice, keep their phrasing and layout; tighten
  claims without changing the tone.

## 3. Corrections

- Fix the claim everywhere it went: thread, ticket, PR description, canvas.
- Structure: what was wrong, what is right, what follows from it.
- Say plainly that readers should disregard the earlier figure.
- Where possible, edit the original and mark it as revised.

## 4. Draft PRs

- Open one only when asked, and as a draft by default.
- The title names the ticket key and includes any release marker the
  repository requires.
- Commit generated outputs together with the change that produces them.
- State dependencies, merge order, and any cost approval that is needed.

## 5. Closures and no action

- "No action" is a valid outcome. Record the evidence and the reason (rare,
  self-recovering, fixed upstream, or costs more than it saves) and propose the
  closing status.
- For a noisy alert, choose between a downtime, a suppression, a monitor
  adjustment or nothing, and explain why each alternative was rejected.
- Never silence a genuine availability or data-loss signal just to reduce
  noise.
- Every downtime has an end time and links a ticket.

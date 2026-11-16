# Self-improvement report contract

The files below are private and local. They live in the reviewing session's own
files directory and are never committed. Examples show shapes, not real
receipts. Every path is absolute, and every file must remain in place until
`checkpoint.py finish` has verified it.

## `proposal.json`

| Key | Type and rule |
|---|---|
| `run_id` | string returned by `begin` |
| `reviewed_since` | string returned by `begin` |
| `reviewed_through` | string returned by `begin` |
| `coverage.environments` | array holding exactly the ten environment names, with no duplicates |
| `coverage.local` | `complete` |
| `coverage.cloud` | `complete`, `lagging` or `unavailable` |
| `coverage.material_gaps` | `[]` |
| `coverage.sessions_considered` | non-negative integer |
| `coverage.turns_considered` | non-negative integer |
| `themes` | array (informational) |
| `changes` | array, possibly empty, of `{ "path": <absolute>, "summary", "proposed": <text or diff>, "rationale", "check" }` |
| `deferred` | array (informational) |
| `readable_report` | absolute path of the human-readable report |

Rules:

- Per-root coverage rows and the findings belong in the readable report. A list
  of environment names alone does not prove that anything was searched.
- `lagging` or `unavailable` cloud coverage is acceptable only when complete
  local evidence covers the whole window and the report states the limitation.
- Unknown local coverage or any material gap blocks approval and completion.
- The counts describe the inventory that was actually reviewed.
- A change path must be a file inside the verified harness checkout or inside the
  approved private context directory (`~/.config/digits/context`). Duplicates,
  directories and other repositories are rejected.
- Approval covers this exact proposal and its readable report. Editing either
  afterwards requires a new approval.

Shape example:

```json
{
  "run_id": "<32 hex characters from begin>",
  "reviewed_since": "2026-11-04T22:00:00.000000Z",
  "reviewed_through": "2026-11-06T22:00:00.000000Z",
  "coverage": {
    "environments": ["left_pinky", "left_ring", "left_middle", "left_pointer", "left_thumb",
                     "right_thumb", "right_pointer", "right_middle", "right_ring", "right_pinky"],
    "local": "complete",
    "cloud": "lagging",
    "material_gaps": [],
    "sessions_considered": 12,
    "turns_considered": 340
  },
  "themes": [],
  "changes": [],
  "deferred": [],
  "readable_report": "<absolute path>/report.md"
}
```

## `completion.json`

| Key | Type and rule |
|---|---|
| `run_id` | the active run |
| `proposal_sha256` | the hash printed by `approve` |
| `outcome` | `updated` when `changes` is non-empty, otherwise `no_change` |
| `checks` | non-empty array of `{ "command", "result": "passed", "evidence" }` |
| `summary` | short text |

Failed, skipped or pending checks block `finish`. The helper snapshots every
approved file at approval time and rejects `updated` when any of them is
unchanged. It stores hashes and the approval reference, but it cannot prove that
a human approved or that a narrative is true; that stays the agent's duty.

# Provenance

## Origin

Digits started as one engineer's private Copilot CLI setup: a tmux dashboard,
a handful of workflow skills and a growing collection of instructions. That
setup went through several private iterations before it was generalized.

**This repository is a clean-room implementation.** One team studied how the
earlier private version behaved and wrote the specification in `spec/`. A
second team, which never had access to that code, built everything else from
the specification alone. [How it was rebuilt](#how-it-was-rebuilt) below
describes the whole process.

Digits is not an export of anything, nor a copy of anyone's home directory or
dotfiles. It contains nothing specific to an organization: no company or
personal names, internal hosts, repositories, channels or defaults. Only
generic placeholders such as `example-org` and the private-bindings pattern
remain.

## How it was rebuilt

1. **Specification (separate team).** Specification authors studied the
   behavior of a prior, privately maintained implementation and wrote
   functional requirements in `spec/`. These describe interfaces, observable
   behavior, edge cases and acceptance tests. The rules for authors:
   - No source code, configuration bodies or test code was transcribed.
   - No sentence of prior documentation was reused.
   - Interface facts needed for compatibility were allowed: file paths, command
     flags, JSON keys, tmux option names, and host API event names.
2. **Contamination check.** Before implementation started, the specification
   was mechanically compared against the prior implementation for shared word
   sequences. Matches were rewritten unless they were interface identifiers.
3. **Implementation (clean team).** Fresh implementers were given only `spec/`.
   They were instructed not to open, search or read the prior implementation,
   its repositories, installed copies, or caches. All code, tests and
   documentation outside `spec/` were written by them.
4. **Verification.** The implementation was checked against the spec's
   acceptance tests and the repository guards. A similarity scan against the
   prior implementation looked for shared token sequences. Black-box
   comparisons of command-line behavior were run outside the clean team; any
   discrepancy was fed back only as a specification clarification, never as
   code.

The repository history begins with the specification commit, followed by the
implementation commits.
Later housekeeping (adding the MIT license, moving documents, fixing links and
the matching test and spec updates) was done directly by the maintainer and
introduced no material from the prior implementation.

## Design ideas carried forward

Only the following concepts were carried over:

- each environment gets its own full clone, never a shared worktree;
- the dashboard reacts to Copilot lifecycle events instead of polling;
- installers preview before writing, keep receipts of what they own, store
  immutable snapshots and can roll back;
- context is disclosed progressively: a small bootstrap with a route table,
  and pages that are read only when they are relevant;
- approval is given in stages, each one separately; passing CI or a merge
  never implies the next stage;
- helpers are deterministic and tested with mocks, and judgment is left to
  people.

## Deliberately excluded

None of the following exists in this repository, and none of it may be added:

- credentials of any kind, including tokens, OAuth caches, keychain items and
  MCP configuration that contains secrets;
- personal profiles for databases, clouds or tools, and certificate bundles;
- transcripts, session state, logs or any other live runtime state;
- organizational inventories such as repository lists, account or role grants,
  channels, ticket metadata, schedules and staff directories;
- proxies, token helpers or service tooling that only fits one company;
- scheduled jobs, and paths that only make sense on one machine.

Users keep their own equivalents as private bindings in
`~/.config/digits/context/`, and the installers never export them.

## Acknowledgements

Thanks to [Ken Crowell](https://github.com/oeuftete), whose personal agent
harness inspired several of the workflow skills here: investigation framing,
the per-claim challenge pass, assessing review feedback, sweeping draft PRs,
rebasing PRs, updating shared workflows and keeping review reactions current.
Digits reimplements those ideas from its own specification; any mistakes are
its own.

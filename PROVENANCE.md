# Provenance

## Origin

Digits started as one engineer's private Copilot CLI setup: a tmux dashboard,
a handful of workflow skills and a growing collection of instructions. That
setup went through several private iterations before it was generalized.

**This repository is a clean-room implementation.** One team studied how the
earlier private version behaved and wrote the specification in `spec/`. A
second team, which never had access to that code, built everything else from
the specification alone. [CLEAN_ROOM.md](CLEAN_ROOM.md) describes the whole
process: the rules for specification authors, the contamination check, the
isolated implementation and the final verification.

Digits is not an export of anything, nor a copy of anyone's home directory or
dotfiles. It contains nothing specific to an organization: no company or
personal names, internal hosts, repositories, channels or defaults. Only
generic placeholders such as `example-org` and the private-bindings pattern
remain.

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

## Acknowledgements — to be confirmed before publication

> **Placeholder.** The ideas behind several workflow skills (investigation
> framing, the per-claim challenge pass, assessing review feedback, triaging
> draft PRs, rebasing PRs and updating shared workflows) came from patterns in
> another engineer's personal harness. Before publication the maintainers must
> obtain that engineer's consent and preferred wording for the credit, or
> remove the derived material. Completing or deleting this section is an item
> on the [open-source release checklist](docs/open-source-release-checklist.md).

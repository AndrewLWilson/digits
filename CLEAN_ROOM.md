# Clean-room rebuild record

Digits in this repository was rebuilt from scratch using a clean-room process.
It is a new implementation and was not copied or derived line-by-line from any
prior code base.

## Process

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

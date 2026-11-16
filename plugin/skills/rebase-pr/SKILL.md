---
name: rebase-pr
description: Rebase one GitHub pull request onto the current tip of its base branch, with an ownership preflight, a dedicated worktree, conflict resolution that keeps what both sides intended, a semantic review of code that merged cleanly, verification, and a lease-guarded force push bound to the previously recorded head SHA. Use for conflicting or out-of-date PRs and when asked to rebase a PR, bring it up to date, or fix its merge conflicts.
user-invocable: true
---

# Rebase a pull request

Usage: `/digits:rebase-pr <owner/repo#N or PR URL> [push]`

## Authority and pace

- Invoking the skill authorizes a local rebase plus verification, nothing more.
- A lease-protected push of the rewritten branch is authorized only when the
  invocation includes `push` (or asks to update the PR) **and** the user
  authored every commit on the branch. Otherwise ask once, showing the results.
- Never push without a lease, never merge, never rebase a branch another chat
  owns. Natively stacked PRs belong to the built-in `pr-stack` skill.
- Once started, run preflight through report in a single turn. Never say a
  push is happening unless this turn actually performs it.

## Steps

### 1. Preflight (read-only)

```bash
gh pr view <N> --repo <owner/repo> --json headRefOid,baseRefName,headRefName,state,isDraft,mergeable,isCrossRepository,headRepositoryOwner,labels,commits
gh api --hostname github.com "repos/<owner>/<repo>/stacks?pull_request=<N>"
```

Stop and ask when:

- the PR is not open;
- it comes from a fork;
- any commit has an author other than the user;
- a label signals blocked or do-not-merge;
- it belongs to a native stack;
- GitHub already reports `mergeable` as `MERGEABLE` (continue only if the user
  explicitly asked to bring it up to date).

`UNKNOWN` means GitHub has not computed mergeability yet: read it again.

### 2. Choose the checkout

In order of preference:

1. a clean checkout on the head branch that this chat owns;
2. otherwise a new worktree used only for this PR, made with
   `git worktree add` from an existing clone on the head branch. If that branch
   is already checked out in another worktree, create a detached worktree
   (`--detach`) at the head SHA and later push to `HEAD:refs/heads/<head>`.

Never switch, stash or reset another chat's checkout or any dirty clone.

Then fetch `origin` inside the worktree and confirm that the local head,
`origin/<head>` and the preflight SHA all match. Unpushed local commits mean
stop and ask. **Record the old head SHA**; the lease depends on it.

### 3. Understand both sides before editing

```bash
git merge-base HEAD origin/<base>
git log --oneline <merge-base>..origin/<base>
git diff --stat origin/<base>...HEAD
git diff <merge-base> origin/<base> -- <PR files>
```

Work out what each side intended first; resolutions that are mechanically easy
are often semantically wrong.

### 4. Rebase and resolve

```bash
GIT_EDITOR=true git rebase origin/<base> < /dev/null
```

Every conflicting hunk keeps both intents; there is no default side.

- **Same text reworded on both sides** - write one version that carries both.
- **Lock files and generated outputs** (`*.lock`, `uv.lock`, `poetry.lock`,
  `.terraform.lock.hcl`, dbt or OpenAPI outputs, schema dumps) - settle the
  sources first, then regenerate with the repository's own tooling.
- **A path added by both base and PR** - at every stop keep base's version and
  skip commits that become empty; at the end add one commit that folds in the
  PR's content.
- **Ordered or timestamped migrations** - renumber the PR's migrations to
  follow base's latest using a generated sequence, update references, and run
  the repository's migration check as proof.
- **Interrupted commands** - a cancelled command may still have finished the
  rebase; run `git status -sb` before retrying.
- **Semantic read** - for every function the PR touches, read the merged
  version and note anything base introduced that now interacts with the PR's
  behavior (locking, transactions, retries, handlers, contracts,
  configuration). Report these; change them only if a test fails.

### 5. Verify (inside the worktree)

```bash
git grep -nE '^(<<<<<<< |>>>>>>> |=======$)'
git log --format='%h %G? %ae %s' origin/<base>..HEAD
git range-diff origin/<base>...<old-sha> origin/<base>..HEAD
```

Pass criteria: no conflict markers; every author preserved; signature status
acceptable under the repository's policy; the range-diff differs only in the
conflict hunks. Parse every data file you edited. Run lint and the tests that
cover the PR's files and whatever base changed in the same code. A failure
elsewhere counts as environmental only if it reproduces identically on
`origin/<base>`; say which case applies.

### 6. Push

```bash
git push --force-with-lease=refs/heads/<head>:<old-sha> origin HEAD:refs/heads/<head>
```

`<old-sha>` is the SHA recorded in step 2; never push without
`--force-with-lease=refs/heads/<head>:<old-sha>`. Afterwards confirm with
`gh pr view` that the new head is shown, `mergeable` reaches `MERGEABLE` (it
may lag a few seconds), commit verification still holds where required, and CI
has started on the new head. Existing automated reviews are now stale; do not
request a new one unless asked.

### 7. Report

- PR link naming the repository;
- old and new head SHAs and the base commit used;
- for every conflict: the file, what each side changed, and how they were
  combined;
- interactions found in step 4, framed as points for reviewers and not posted
  unless the user asks;
- lint and test results with counts, plus evidence for any environmental
  failure.

## Non-goals

No unleased push, no merge, no stash or reset of foreign checkouts, no
automated re-review request, no posting.

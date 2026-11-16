# Infrastructure ownership and lifecycle

Use when editing infrastructure-as-code, IAM, KMS, or storage; enabling, disabling, or retiring something; planning a rollout; or picking how to validate with ephemeral PR environments.
Scope: preparing source changes and collecting evidence; permission to operate live systems is a separate decision.
Sources: target-repository patterns, maintainer agreements, `https://www.pulumi.com/docs/iac/concepts/resources/options/protect/`, and `https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_control-access_disable-perms.html`.
Reviewed: 2026-11-16.
Recheck: the source ref, the real stack or checkpoint, resource flags, preview output, and approval.

Decision procedure:

1. Identify the owning layer and repository for every resource involved.
2. Classify the work: locally preparable source change, gated deployment, or pending
   stakeholder contract.
3. Choose the narrowest validation that exercises the change.
4. Confirm lifecycle policy, execution path, and dependency order from existing source.
5. Before anything live, pin the rollout evidence and the single execution owner.

## Find the owning layer before calling something blocked

- Map each resource to its owners: which family of accounts and which environment, the
  tenant, the database or storage prefix, who writes it, which identity reads it, and
  which IaC repository is accountable. The
  [repository map](../references/repository-map.md) and the
  [data warehouse page](../domains/data-warehouse.md) help; concrete identities come from
  private bindings. Lookalike names say nothing about whether an account, stack, role, or
  owner is actually shared.
- A trial serving one consumer belongs outside the general tenant APIs unless broad reuse
  is a real need, and an owning repository should not grow a new environment just to
  host something short-lived. If explicitly approved, a hand-made exception can cover only
  the resource the IaC cannot express, with established IaC still handling everything
  else; the workstream notes who owns it, how far it reaches, when it lapses, and how it
  gets removed. Such an exception neither blesses hand-built infrastructure in general nor
  stands in for a permanent production owner.
- Tell three cases apart: (a) source work you can ready locally under today's approval;
  (b) a deploy or in-platform check that depends on access or a time slot you lack or
  have not been granted; (c) a provisional contract still waiting on stakeholders. Cases
  (b) and (c) are not, by themselves, a reason to hold back a reviewable candidate.
- Being allowed to edit the IaC repository does not mean you may apply it, nor that you
  may route around a denied read. On a denial, stop that action and say which access is
  missing. Running a preview against a live or shared stack, or passing a
  service-integration gate, each needs separately scoped approval; permission to read
  does not include permission to preview. Locally mocked tests sit on a different side of
  that line.

## Keep ephemeral PR validation representative

- When tradeoffs are material or the mechanism is unclear, work through
  [engineering decisions](engineering-decisions.md) before choosing an implementation.
- Some repositories build a separate environment for each PR, guarded by approvals.
  Approving all of those variants is not the default, because the combined cost is high.
  Start by asking whether a deployment is needed at all; normal CI and local tests can be
  enough.
- When live validation is required and approved, one representative environment and
  program pair (say `dev` with `app`) is usually enough, provided it exercises the change.
  That pairing is only an illustration: a data change needs data-relevant coverage. Read
  the current workflow and pick the narrowest relevant scope.
- Run extra variants only to close a specific coverage gap or meet an explicit
  requirement, and only within approved scope. A request to validate a PR is not a
  request to approve all its gates. Leave unneeded gates unapproved, never bypass
  required CI, and never describe variants that did not run as tested.

## Minimize cross-system configuration handoffs

- Classify inputs before adding configuration. Account-wide identities belong in
  verified platform or account settings; per-tenant files hold durable tenant decisions
  such as explicitly enabling a feature. Do not copy shared identity into each tenant,
  and never treat a failed lookup as "disabled". Missing required configuration should
  make enabled operations fail; absent or disabled features should do nothing.
- Before designing a circular "copy the outputs back in" bootstrap, read the inputs the
  pinned provider documents and the helpers that already exist. Keep provider-generated
  identity contracts, and consume reviewed outputs or remote state rather than copying
  values by hand. Where compatible, deliberately matching identifiers can remove a
  handoff, scoped by tenant, environment, and purpose; but do not replace generated
  identities just to simplify bootstrapping. An external ID is not a secret; keep
  privilege scopes apart; verify where each principal comes from and who can create
  integrations; an unguessable identifier authorizes nothing.
- When several storage integrations inside a single warehouse account rely on the same
  cloud principal, use the guidance in
  [Storage and notebook trials](../domains/data-warehouse.md#storage-and-notebook-trials).
- Treat creating the identity and granting access as separate stages. Stage one makes
  the integration identity but holds back stages, functions, and grants. Stage two sets
  up the trust relationship and permissions where the data lives and checks them. Stage
  three opens consumer access, and only via the reviewed deployment route. Keep track of
  where each environment stands. Neither generated outputs nor switched-on flags
  demonstrate that the consumer can really read the data it is meant to.
- Build on the IAM and policy helpers the repository already has. Plain mock tests that
  CI executes, covering gates, trust conditions, and permission bounds, are worth more
  than a custom emulator that mostly gets skipped. Save dedicated integration tests for
  behaviour ordinary tests cannot reveal, and remember that no mock proves deployed access.
- Repository-level design and configuration contracts should be short and change rarely.
  Sequencing for a single rollout, who has approved what, and how it will be executed
  belong in the ticket or workstream, although a runbook that is reusable and tested can
  live in the repository. Writing more documentation never makes up for absent
  operational evidence.

## Review access surfaces and trial expiry

- Evaluate listing, object reads, writes or deletes, and KMS decryption separately. The
  stage URL does not bound what is ultimately readable: a broad listing prefix can expose
  keys outside the target even when IAM restricts content reads to intended paths. Object
  keys can be sensitive themselves; hand them off safely as described in
  [Exports, removals, and delivery](../domains/data-warehouse.md#exports-removals-and-delivery).
- Granting one member versus all members is a population decision, not two
  interchangeable forms of "sampling".
- Check the encryption of the existing objects you actually need, not only the bucket's
  default. Restrict decryption to the verified key and intended service path. Inspect key,
  bucket, and network policies without broadly loosening them to make a read work.
- Time-boxed trials must block both new role assumptions and the S3/KMS calls existing
  sessions could still make; removing trust does not revoke credentials already issued.
  Tests should show access working before the deadline, refused at and after it, and
  refused outside the intended scope. Results from a policy simulator are not proof that
  access works from end to end. Reaching the deadline removes no resources and does not
  wipe data that was cached or downloaded, so cleanup needs a named owner.

## Preserve the existing lifecycle policy

- Read the nearest existing helper and its tests (a deletion-protection helper, a
  per-tenant convention) before writing new policy, instead of assuming `protect: true`
  everywhere is safer. Keep resource identity and ownership stable; invent no bypass flags.
- Test transitions from existing state, not just fresh registration: create, update,
  change protection, disable or retire; defaults and intended production exceptions; and
  restart, retry, and idempotence where required. A test that merely mirrors new code can
  cement the bug.
- Pulumi needs two steps: first an update that clears protection, and only in a
  subsequent update can the resource be deleted. Throughout the protection change the
  resource remains in source; removing it from code is not the same as unprotecting it.
  This shapes source, tests, and runbooks; it does not permit unprotecting anything live.
  Pausing refreshes or exports is different from deleting schemas, grants, or storage.

## Validate the execution path and dependency order

- Ahead of any local IaC check, look up the commands the repository specifies, the
  versions it pins for providers and tools, how its backend is configured, and which
  workspace or stack has been confirmed as correct. Follow the repository's usual
  isolated route; when initializing would overwrite backend metadata in the checkout you
  are working in, use a disposable copy of the source instead. Switching the backend off
  is no excuse to re-initialize the real checkout or to pick a workspace by guesswork. A
  check that passed locally never licenses a plan against live infrastructure.
- Treat the plan and apply workflows as design inputs. Find out which artifacts,
  generated files, and paths actually survive the hop between jobs; something you can see
  locally may never reach the apply job. Keep generated contracts in step with their
  source by running the existing generator. Learn whether a PR push changes shared dev
  targets and whether recovery or rollback steps could collide with another run. Keep
  exactly one execution owner: never start a parallel apply or cancel a whole shared
  deployment to unstick a check.
- When a change crosses repositories, write down what it depends on (a resource or an
  API), which release will deliver that dependency, the way consumers will pick it up,
  and how you will confirm they accepted it. The dependency ships before any consumer is
  switched on; on removal, consumers are halted or moved first and the dependency goes
  last. Verify the actual release and deployment order instead of assuming one release
  carries both safely; remember tenants that skip releases and old consumers still running.
  Inspect replace and delete ordering in the dependency graph (source order proves
  nothing). Where the verified provider or service contract requires it, use staged updates
  that keep the live dependency rather than repointing and deleting in one untested step.
- Name the last reversible step, the rollback target, and any restore or replay need;
  reverting code may not restore deleted data or undo an incompatible migration. These are
  design and runbook requirements, not approval to deploy or recover.

## Rollout evidence and single execution owner

- Settle these facts before a live preview, apply, or deployment: precisely which
  reviewed source or image goes out, the checkpoint as it stands now, the resources and
  settings that have to survive, what change you expect, which target was approved, and
  the person running it. Pushing or merging can set off infrastructure jobs unrelated to
  the task; raise them before you count on an approval. For shared targets, coordinate
  with the helper that ships in the `inter-env` skill rather than sending keystrokes to
  tmux yourself.
- Green results from an isolated schema build in CI do not bring back the canonical dev
  environment and do not count as a tenant accepting the change. Check workflow jobs, the
  installed program or image, endpoint and resource state, consumer access, and whether
  data behaves as intended. Stop on unexpected preview differences. Read the actual source
  and configuration rather than PR text, which can still contain outdated placeholders or
  describe less than the change really does.
- Do not merge, approve gates, rerun migrations, bring in extra runners, or touch table or
  schedule state for the sole purpose of making some unrelated PR pass.
- When blocked, record the exact next gate and its owner using the
  [continuity workflow](continuity.md). Keep rollback evidence, but do not restate an
  unchanged rollback plan in every update.

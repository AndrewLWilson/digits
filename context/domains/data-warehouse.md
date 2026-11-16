# Data warehouse, dbt, and dataset delivery

Use when choosing a warehouse connection or source, explaining an apparently missing table or role, drafting or proposing SQL, checking dbt models, preparing a notebook or storage trial, exporting or delivering data, or validating analysis findings.
Scope: evidence gathering and source preparation only; concrete identifiers live in the private bindings, not on this page.
Sources: share definitions and present-day IaC, the private `data-warehouse-bindings.md` file, the dbt profile reference (https://docs.getdbt.com/docs/local/profiles.yml), and the Snowflake S3 storage-integration guide (https://docs.snowflake.com/en/user-guide/data-load-s3-config-storage-integration).
Reviewed: 2026-11-16.
Recheck: tenant, environment, account family, profile, source/ref, and which authorization applies today.

Decision procedure:

1. Read `{{PRIVATE_ROOT}}/data-warehouse-bindings.md`, then `{{HOME}}/.dbt/profiles.yml`, then the relevant definitions.
2. Settle identity (account family, environment, tenant, database) and the producer → share → consumer chain before picking source, credential, compute, or target. If a binding is missing, ask the user.
3. Confirm identifiers with cheap metadata; propose anything costly or production-facing for the user to run.
4. For trials, exports, removals, and findings, follow the matching section below and keep each claim tied to the evidence that actually supports it.

Common pitfalls: treating a dev account's missing production database as a broken source, retrying a failed query under another role, and calling a broad bucket listing a deletion list.

## Establish identity before querying or proposing new storage

- Work in this order: the binding file first, the local dbt profile second, the relevant definitions third. Only once the four-part identity — account family, environment, tenant, database — and the producer-to-share-to-consumer path are settled may you choose a source, credential, compute, or target. When no binding covers the case, ask; never invent one.
- A tenant is not an account. One account may host several isolated tenants, and a dev tenant is never consumer production. Repository and folder names are not reliable signals of the account family.
- A production database that does not appear in a dev account is the normal state of affairs. It does not show that a source is missing, and it is no reason to add a source or a storage mapping. Remember also that some downstream inputs never travel through the upstream share.
- The [repository map](../references/repository-map.md) tells you where definitions live. Knowing it never licenses switching tenant or account, elevating privileges, reading production, or deploying. When access fails, stop and report — do not retry with another account or role.

## Queries, identifiers, and cost

- Before you run SQL or hand it to someone, confirm every identifier with cheap metadata (`SHOW`, `DESCRIBE`, the information schema) or authoritative object documentation. Do not guess columns, views, or functions.
- SQL handed to people for validation names concrete `database.schema.table` objects, not dbt `ref()` or `source()` macros.
- Cheap metadata lookups are fine to run yourself. Anything expensive or touching production — discovery queries and config lookups included — is proposed for the user to run, with a cost estimate (for example `EXPLAIN` bytes) and a statement timeout.
- Use the ad hoc compute approved in the bindings. When a query is slow, make it narrower; do not move to production-sized compute.
- For code someone else will run and you cannot (notebooks, worksheets): state the role, account, compute, and expected runtime; verify grants from the role to the compute and stage, and confirm API support (for instance internal versus external stage operations) from metadata or docs first; start with a small probe that prints column names and sizes; cap samples; and print progress while it runs.

## Local profile and isolation

- Read the user's profile at `{{HOME}}/.dbt/profiles.yml` before touching any dbt configuration.
- dbt's profile lookup order varies by version: `--profiles-dir` on the command line, then (in some versions) `DBT_PROFILES_DIR`, then the project directory, then `~/.dbt/`. A `profiles.yml` sitting in the project root can therefore shadow the user's own. Read the docs for the dbt version the repository pins, not the latest release.
- Prefer interactive SSO or another approved interactive method; profiles never contain secrets. Hosts or account locators, the default tenant, compute, and any corporate CA bundle are facts taken from the bindings, not inferred from display names.
- Package downloads use the approved CA bundle. Never disable TLS verification. Ask before changing the default tenant.
- Every checkout has its own development schema, following a pattern like `dev_<user>_<finger>`, derived from the selected clone — never inherited from some unrelated terminal. The naming convention and any shell hook that maintains it are recorded in the bindings.
- Repositories can add their own schema rules on top. Local runs never write to shared or production schemas.

## Storage and notebook trials

- Decide first whether the trial only proves connectivity or actually processes representative test data; choose infrastructure afterwards.
- Pin down: source and notebook environments, data classification and its approval, file types and sample size, the read and write capabilities needed, and acceptance criteria.
- A "sandbox" or "preview" label proves neither that the data is synthetic nor that it lives in a dev account. Do not take the shortcut of pointing production compute at dev buckets; pick the approved environment that matches.
- Certain warehouses give all storage integrations within one account a single shared cloud principal. Keep each integration's existing generated external ID, and derive the trust policy on the source side from reviewed IaC outputs or from remote state. The shared principal alone cannot distinguish integrations, so find out who can create them. Recreating an integration may produce a new generated external ID.
- Hold back stages, functions, and grants until source-side trust is verified; see [infrastructure lifecycle](../workflows/infra-lifecycle.md).
- Check everything the intended role needs: usage on database and schema, grants on stages and functions, compute, and any external-access integration, secrets, or licence the account requires. Reuse existing prerequisite grants; never silently broaden the role or introduce a second owner for the same grant.
- An existing stage and a successful approved operation are separate pieces of evidence. A read-only slice proves neither that write-back works nor that de-identification is accepted.

## Model and deployment evidence

- Inspect compiled and deployed SQL plus the materialization history. A filter that exists in source is no proof that the table got rebuilt using it.
- Passing unit, parse, or isolated-CI checks does not amount to approved acceptance in the live system, and the duration of an incremental CI run says nothing about a full-history rebuild.
- Generated inventories come from the existing metadata or manifest generators; never hand-edit them.
- Production deployments that have their own release sequence follow the [organization release procedures](../workflows/github-delivery.md#organization-release-procedures). A normal release is not that deployment, and neither is a green CI schema build.

## Exports, removals, and delivery

- State the population, when eligibility is evaluated, the source layers, the recipient, the immutable delivery or version, and the evidence required. Trace the chain: producer, materialized cohort, export, transfer, consumer.
- A successful export says nothing about receipt, eligibility, attachment linkage, or consumption. Do not presume each member ought to have a resource, and do not blame an absent one on a fetching defect, until source, retention, and eligibility evidence backs that up.
- Respect legal holds, retention rules, consent, and deletion requests. Attachments are not necessarily covered just because a hold applies to the tabular rows. An unrelated green workflow never satisfies an eligibility gate. Whenever you unblock something temporarily, connect it to the lasting fix and to the way that fix will be checked.
- Bucket or export listings are discovery sets; they do not prove every object contains affected people. Before handing off a removal, cover the full interval and every relevant project, export, and transfer; trace membership through exact snapshots; and treat files that mix members (which may need a filtered rebuild) differently from binary attachments.
- Label broad inventories "review candidates", never "ready to delete".
- Object keys may contain sensitive titles. In handoffs use opaque IDs, version IDs, hashed exact keys, and the metadata you expect; only the executor's authorized runtime should turn these back into real keys.
- Sign-off on an inventory is not sign-off on deleting anything. Require a dry run and explicit approval of the resolved object and version list.
- Every count names its source, unit, population, time window with zone, and duplicate handling. Keep original-only, backfill-only, overlapping, and full populations apart; extra rows may be duplicates, gap fills, or out-of-window records. Reuse the source's exact classification words — "selected" or "in scope" never turns into "affected".
- Confirm delivery by exact export, run, and version identities and by comparing expected against observed keys, sizes, and checksums. A manifest on local disk is neither an uploaded manifest nor a sent notification.
- For freshness questions, distinguish new failures, recovered old records, stale audit sources, and intervals nobody observed.
- Do not rerun a completed export, grant, or recovery just because an old handoff mentions it; reconcile through [continuity](../workflows/continuity.md).

## Validate analyses separately

- High-stakes findings (regulated, clinical, financial, or customer-facing) get three separate validations: the data, the code, and the findings. Passing SQL tests validate only the code.
- Record each problem and fix it, or obtain approval for the limitations that are acceptable.
- Where the organization requires independent review, it must come from another qualified person; a second AI agent does not count. Never claim human review happened when it did not. Use the organization's controlled procedure when one exists.
- Routine engineering reports are exempt from these requirements.
- Present results as described in [reader-first writing](../references/writing.md).

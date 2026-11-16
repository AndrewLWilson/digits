# Data warehouse bindings (example)

Private, non-secret, machine-local facts. Every value below is fictional: replace each one only after verifying it, never commit the filled copy, and never add credentials (use SSO or a secret store).

## Account families and tenants

| Account family | Environment | Account locator / host | Tenants | Databases | Provenance |
|---|---|---|---|---|---|
| Producer | dev | `exampleorg-producer-dev` | `acme`, `globex` | `ACME_DEV`, `GLOBEX_DEV` | `example-org/infra-warehouse` at `b7c8d9e`, 2026-01-15 |
| Producer | prod | `exampleorg-producer-prod` | `acme`, `globex` | `ACME_PROD`, `GLOBEX_PROD` | `example-org/infra-warehouse` at `b7c8d9e`, 2026-01-15 |
| Consumer | prod | `exampleorg-consumer-prod` | `acme` | `ACME_ANALYTICS` (imports the producer share) | Share definition in `example-org/infra-tenants`, 2026-01-15 |

Tenants and accounts are different things: one account can hold several tenants. Local
work defaults to tenant `acme`; changing that default needs the user's confirmation.

## Local dbt profile

| Fact | Value | Provenance |
|---|---|---|
| Profiles directory | `~/.dbt` (pass `--profiles-dir ~/.dbt` when the project root has its own profile file) | `dbt debug`, 2026-01-15 |
| Authentication | SSO (`externalbrowser`); the profile holds no secrets | `~/.dbt/profiles.yml`, 2026-01-15 |
| Development schema convention | `dev_<user>_<finger>`, for example `dev_jdoe_left_thumb`, kept current by the fictional shell hook `example-dbt-schema` | Shell config, 2026-01-15 |
| Corporate CA bundle for package downloads | `~/.config/example-org/ca-bundle.pem` | IT onboarding page, 2026-01-15 |

## Compute and roles

| Purpose | Compute | Role | Provenance |
|---|---|---|---|
| Approved ad hoc queries and local development | `ADHOC_XS` | `DEVELOPER` | Access request `PROJ-7`, 2026-01-15 |
| Production pipelines only (never ad hoc work) | `PIPELINE_L` | `TRANSFORMER` | `example-org/infra-warehouse` at `b7c8d9e`, 2026-01-15 |

## Validation requirements

| Analysis type | Requirement | Provenance |
|---|---|---|
| Customer-facing findings | Validate data, code and findings separately; an independent human reviewer signs off | Analytics review policy, 2026-01-15 |

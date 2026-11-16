# Tool and repository bindings (example)

Private, non-secret, machine-local facts. Every value below is fictional: replace each one only after verifying it, never commit the filled copy, and never add credentials.

## User and shell

| Fact | Value | Provenance |
|---|---|---|
| Shell for commands given to the user | `zsh` (when this row is absent, agents use POSIX `sh`) | `echo $SHELL`, 2026-01-15 |
| Legacy checkout roots (not environment roots, never a fallback) | `~/code` | `ls ~`, 2026-01-15 |
| Repository inventory / drift helper | `~/.local/bin/example-drift`, manifest `~/.config/example-drift/repos.txt` | `example-drift --help`, 2026-01-15 |

## GitHub and repositories

| Repository | Default branch | Release / bump rule | Automated review (trigger, size cap) | Provenance |
|---|---|---|---|---|
| `example-org/data-models` | `main` | `#patch` or `#minor` must appear in the squash commit message | AI review on non-draft PR opened/synchronize; skipped at 1,000 or more changed lines | `.github/workflows/release.yml` and `review.yml` at `a1b2c3d`, 2026-01-15 |
| `example-org/infra-warehouse` | `trunk` | Releases by tag only | Runs when a member comments `/review` | `.github/workflows/review.yml` at `d4e5f6a`, 2026-01-15 |

Organization release procedures and the real repository map may also be kept here, each
row dated.

## Issue tracker

| Fact | Value | Provenance |
|---|---|---|
| Site | `https://example-org.example` (fictional) | Tracker profile page, 2026-01-15 |
| Default project / issue type | `PROJ` / Task | Team agreement, 2026-01-15 |
| Fields required at creation | Parent epic; Risk (Low, Medium, High); Team = Platform; Component = Data | Project create screen, 2026-01-15 |
| Field-ID hints (confirm against live metadata) | Risk `<customfield-id>` options `<option-ids>`; Team `<customfield-id>` | Create metadata call, 2026-01-15 |
| Weekly priorities filter | `labels = "this-week" ORDER BY Rank ASC` | Saved team filter, 2026-01-15 |
| Access-escalation tickets | Required before any new elevated role | Access policy page, 2026-01-15 |

## Chat and integrations

| Fact | Value | Provenance |
|---|---|---|
| Review-request channel | `#example-reviews` | Team handbook, 2026-01-15 |
| MCP servers in use | GitHub, Jira, Slack | Local MCP config file, 2026-01-15 |

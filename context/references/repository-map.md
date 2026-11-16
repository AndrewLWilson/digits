# Repository responsibility map (template)

Use when looking for source code, the IaC that owns a resource, deployment workflows, generated metadata, or related work across repositories.
Scope: location hints for a workspace with many repositories; it does not say who owns a task or PR right now.
Sources: verified clone origins and the definitions each row links to.
Reviewed: 2026-11-16; every row below is fictional.
Recheck: the chosen checkout, its default branch, the definitions, and current ownership before changing anything.

Decision procedure:

1. Find the candidate row, then open the checkout inside the environment root you selected.
2. Search that repository's code and instructions for existing generators and validation commands before writing anything new.
3. Confirm branch, data, and infrastructure ownership on the linked pages before acting.

## How to use and maintain this map

- The rows below describe an invented organization, `example-org`, purely to show how much detail is useful. A real inventory belongs only in private material — the tool binding under `{{PRIVATE_ROOT}}`, or a private fork whose table supersedes this one; public copies never carry it.
- A helpful real row links the repository, says where to start reading, and names the boundary people most often confuse. When citing where an architecture claim came from, use links pinned to a commit.
- Local paths sit inside the active environment root you selected, never in a shared worktree. When two organizations publish repositories with the same name, clone them as `organization--repository`.
- This map only locates code. It tells you nothing about who owns a PR today, what is currently deployed, or what has been approved.

## Example rows (fictional)

| Repository | Where to start and what it owns |
|---|---|
| `example-org/data-models` | Warehouse models and the interfaces they publish. Its deploy workflow spawns a separate deployment for each tenant. Default branch `main`. |
| `example-org/analytics-consumer` | Consumer-side models that read the published share. Its `platform` folder belongs to the consumer, despite what the name implies. |
| `example-org/infra-tenants` | Per-tenant cloud and warehouse infrastructure, share boundaries, and deletion-protection helpers. Each PR gets an ephemeral deploy that waits on approvals. |
| `example-org/infra-warehouse` | Warehouse accounts, roles, and storage integrations. Default branch `trunk`. |
| `other-org/infra-warehouse` | An unrelated repository that happens to share the name; cloned into `other-org--infra-warehouse`. Never mix its refs with the `example-org` repository. |
| `example-org/shared-runtime` | Library and image consumed both by pinned users and by users tracking `latest`. It also carries the database migrations. |
| `example-org/ci-workflows` | Shared CI and deployment workflows, along with pointers to published execution images; downstream repositories lock to a tag. |
| `example-org/platform-docs` | Runbooks and architecture write-ups; verify that the code they point at still reflects current infrastructure. |

## Before relying on a row

- Search the real code and instructions for generators and validation commands that already exist. A resource's name is not evidence of which repository owns it. If an earlier conversation could not locate the existing tool, that is no reason to author another script.
- Check branch and release rules in [GitHub delivery](../workflows/github-delivery.md).
- Check data ownership in [data warehouse](../domains/data-warehouse.md).
- Check infrastructure ownership in [infrastructure lifecycle](../workflows/infra-lifecycle.md).

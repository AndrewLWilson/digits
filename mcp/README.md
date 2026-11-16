# MCP integration recipes

This page is guidance for setting up integrations. It is not an export of
anyone's credentials and not a configuration to switch on as it stands.
[mcp-config.example.json](mcp-config.example.json) illustrates the structure
Copilot CLI expects, but it is still full of placeholders and must never be
loaded without editing. Enable only the services you actually need, and leave
any unrelated entries in your personal client file untouched.

## Ground rules

- **Secrets live outside Git.** Keep tokens in the operating-system keychain,
  in a password manager, or in environment variables supplied when the client
  starts. Prefer OAuth whenever both the service and the client support it.
  Any local file that holds a secret must live outside the repository and be
  readable only by you (for example mode 600).
- **Working MCP files are never committed.** Do not copy any of these into a
  repository: your user file `~/.copilot/mcp-config.json`, OAuth cache
  directories such as `~/.copilot/mcp-oauth-config/`, credential headers that
  belong to plugins, or backup copies of any configuration. The repository
  guard refuses the usual file names and the secret guard looks for
  credential-shaped strings, but a human review is still required.
- **Only your own access.** Never reuse values taken from a colleague's
  account. While troubleshooting, never print or display a secret.
- **Prove it with something harmless.** The first check for every integration
  is a small read-only call on data you can already see. Setting up an
  integration involves no writing, posting or deleting.
- **An empty tool list proves nothing.** Clients may load or defer tool lists
  lazily, so a list can look empty. Look at the client's MCP status and run
  tool discovery before deciding a server is broken or missing.
- **A denial is a stopping point.** When authentication, permissions or the
  connection fail, stop and say which access or setup step is missing. Never
  try another account, role, token or path to get around it.
- **Valid syntax is only step one.** Keep four milestones apart: the file
  parses, the tools are discovered, you are authenticated, and an authorized
  call succeeds. CI in this repository never calls live services.

## Client configuration

Copilot CLI reads its per-user server list from `~/.copilot/mcp-config.json`.
More servers can come from workspace-level files or from the
`--additional-mcp-config` flag. All of these files use the same top-level key,
`mcpServers`.

- Hosted servers declare `type` `http` (or `sse`), a `url`, and optionally
  `headers`.
- Servers launched on your machine declare `type` `local`, plus `command`,
  `args`, `env` and, when needed, `cwd`.
- `tools` limits which tools are exposed. Leaving it out exposes every tool,
  the same as `["*"]`. For servers that can change data, list only tools you
  have reviewed.
- Other clients, such as VS Code, have their own formats; dropping a Copilot
  CLI file into them does nothing.
- Choose server names that do not clash with servers that are built in or
  provided by plugins.

The example contains two real hosted endpoints published by their vendors and
two deliberately fake entries that show where local values belong.

| Entry | Source | Authentication | Harmless verification |
|---|---|---|---|
| `atlassian` | [vendor repository](https://github.com/atlassian/atlassian-mcp-server); endpoint `https://mcp.atlassian.com/v2/mcp` | Per-user OAuth inside the client; pick a site you are entitled to use | List the tools, then fetch one issue you can already view |
| `slack` | [vendor documentation](https://docs.slack.dev/ai/slack-mcp-server/); endpoint `https://mcp.slack.com/mcp` | OAuth through an app your workspace allows, following the vendor's instructions for your client | List the tools, then read one channel you are a member of |
| `example-remote` | Fake host under `example.invalid` | Header value supplied only in local configuration | — |
| `example-local` | Fake command and package | Environment value supplied only in local configuration | — |

- GitHub needs no entry, because Copilot CLI already bundles its MCP server.
- When a vendor distributes a plugin that brings its own MCP setup, install
  that plugin from the vendor's supported source instead of copying its
  configuration here.
- Strings such as `__SET_IN_LOCAL_CONFIG__` are not expanded by anything.
  Replace them with real values using whatever mechanism your client supports,
  or delete the entry.
- Pin locally launched packages to a version someone has reviewed; never use
  "latest".

## Recipe template

Copy the block below to document another integration. If the filled-in recipe
names details of your organization, keep that copy in your private bindings.

```markdown
### <Service name>

- **Source and transport:** <vendor URL or package@version>; <http | sse | local>
- **Official documentation:** <link to the vendor's current setup page>
- **Authentication:** <OAuth, keychain-held token, or environment variable name>; <where the secret is stored locally>; <who grants access>
- **Local configuration:** <server name>; <tools allowlist>; <non-secret settings>
- **Harmless verification:** <one read-only request against data you can already see>
- **Failure handling:** <how a denial shows up>; <whom to ask> (never swap credentials)
- **Write capabilities:** <tools that can change data>; <the approval that guards them>
```

## References

- [Adding MCP servers to Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers)
- [Finding and installing Copilot CLI plugins](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing)
- [Model Context Protocol](https://modelcontextprotocol.io/)

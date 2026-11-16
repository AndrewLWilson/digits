# Security policy

## Reporting a vulnerability

**Do not report security problems in public issues.**

Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
instead: open the repository's **Security** tab and choose **Report a
vulnerability**. If that is not available, contact the maintainers privately.

Please include the affected component, the version or commit, the steps to
reproduce the problem and the impact you observed.

**Never paste real secrets, tokens or personal data into a report.** Describe
them or redact them instead.

The maintainers aim to acknowledge reports quickly and to coordinate
disclosure once a fix has been released.

## Scope and expectations

- The dashboard extension, the plugin extensions and the skill helpers are
  executable code that runs with your own permissions. Read them before you
  install them, and read updates before you reload them.
- The installers preview by default and refuse to overwrite files they do not
  own. Any way to get around those protections is in scope.
- A committed credential is never acceptable. If you find one in the tree or
  in the history, report it privately so it can be rotated and purged.
- Problems in third-party services, MCP servers or Copilot CLI itself should
  be reported to the vendor concerned.

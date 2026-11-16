#!/usr/bin/env python3
"""Read-only status snapshot of draft pull requests, one JSON line per PR.

Usage:
    pr_status.py [owner/repo#N ...]

With no targets, every open draft PR authored by the gh-authenticated user is
inspected (via ``gh search prs``). For each PR the helper fetches review,
thread, label, commit and CI data through ``gh api graphql``, classifies it
into a "next move" bucket, and prints one JSON object per line (sorted keys).

A PR that cannot be read yields a record with ``bucket: "error"``; the exit
status is then 1, otherwise 0. The helper never writes to GitHub.
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

GH_TIMEOUT = 60
UNKNOWN_RETRY_DELAY = 3
ERROR_LIMIT = 300

TARGET_RE = re.compile(r"([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)#([0-9]+)")

AUTOMATED_LOGINS = frozenset(
    {
        "github-advanced-security",
        "copilot-swe-agent",
        "github-actions",
        "copilot-pull-request-reviewer",
    }
)

BLOCKING_LABELS = frozenset({"blocked", "do not merge", "do-not-merge", "on hold"})

HINT_RE = re.compile(
    r"depends on(?!:?\s*(?:nothing|none|n/a)\b):?\s*[^\n]{1,120}"
    r"|blocked by[^\n]{0,100}"
    r"|stacked on[^\n]{0,100}"
    r"|do not merge[^\n]{0,80}"
    r"|must not merge[^\n]{0,80}"
    r"|before merg(?:ing|e)[^\n]{0,120}",
    re.IGNORECASE,
)
MAX_HINTS = 4

QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      url
      title
      isDraft
      state
      mergeable
      baseRefName
      headRefName
      headRefOid
      body
      labels(first: 20) { nodes { name } }
      reviewRequests(first: 20) {
        nodes {
          requestedReviewer {
            __typename
            ... on User { login }
            ... on Bot { login }
            ... on Team { slug }
          }
        }
      }
      reviews(last: 50) {
        nodes {
          state
          submittedAt
          commit { oid }
          author { login }
        }
      }
      reviewThreads(first: 100) {
        nodes {
          isOutdated
          isResolved
          comments(first: 30) {
            nodes {
              body
              path
              author { login }
            }
          }
        }
      }
      commits(last: 30) {
        nodes {
          commit {
            oid
            messageHeadline
            committedDate
            authoredDate
            parents { totalCount }
            statusCheckRollup { state }
          }
        }
      }
    }
  }
}
"""

sleep = time.sleep


def is_automated(login):
    """Return True when a GitHub login belongs to a bot or AI reviewer."""
    if not login:
        return False
    return (
        "copilot" in login.lower()
        or login.endswith("[bot]")
        or login in AUTOMATED_LOGINS
    )


_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$",
    re.IGNORECASE,
)


def parse_time(text):
    """Parse an ISO 8601 timestamp into an aware datetime (naive means UTC)."""
    match = _TS_RE.match(text.strip())
    if not match:
        raise ValueError("unrecognized timestamp: %r" % (text,))
    date_part, time_part, fraction, zone = match.groups()
    value = datetime.strptime(date_part + "T" + time_part, "%Y-%m-%dT%H:%M:%S")
    if fraction:
        value = value.replace(microsecond=int((fraction + "000000")[:6]))
    if not zone or zone.upper() == "Z":
        return value.replace(tzinfo=timezone.utc)
    sign = 1 if zone[0] == "+" else -1
    digits = zone[1:].replace(":", "")
    offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return value.replace(tzinfo=timezone(sign * offset))


def _login(actor):
    if not actor:
        return ""
    return actor.get("login") or ""


def dependency_hints(body):
    hints = []
    for match in HINT_RE.finditer(body or ""):
        hints.append(match.group(0).strip())
        if len(hints) == MAX_HINTS:
            break
    return hints


def _open_threads(pr):
    threads = []
    for thread in pr["reviewThreads"]["nodes"]:
        if thread["isResolved"] or thread["isOutdated"]:
            continue
        comments = thread["comments"]["nodes"]
        if not comments:
            continue
        first, last = comments[0], comments[-1]
        author = _login(first.get("author"))
        threads.append(
            {
                "author": author,
                "automated": is_automated(author),
                "body": (first.get("body") or "")[:160],
                "lastAuthor": _login(last.get("author")),
                "path": first.get("path"),
            }
        )
    return threads


def _bucket(labels, hints, mergeable, automated_requested, minutes, ci,
            awaiting, has_automated_review, commits_after):
    if any(label.lower() in BLOCKING_LABELS for label in labels):
        return "skip-blocked-label"
    if hints:
        return "check-dependency"
    if mergeable == "CONFLICTING":
        return "rebase"
    if automated_requested:
        return "review-in-flight"
    if minutes < 15:
        return "check-active-elsewhere"
    if ci in ("FAILURE", "ERROR"):
        return "fix-ci"
    if ci in ("PENDING", "EXPECTED"):
        return "ci-pending"
    if awaiting:
        return "to-assess"
    if not has_automated_review:
        return "no-automated-review"
    if commits_after:
        return "check-stale-review"
    return "ready-candidate"


def classify(pr, me, now):
    """Classify one ``pullRequest`` GraphQL object; returns the output record."""
    labels = [node["name"] for node in pr["labels"]["nodes"]]

    commits = [node["commit"] for node in pr["commits"]["nodes"]]
    head = commits[-1] if commits else None
    ci = None
    if head is not None and head.get("statusCheckRollup"):
        ci = head["statusCheckRollup"]["state"]

    automated_reviews = [
        review for review in pr["reviews"]["nodes"]
        if is_automated(_login(review.get("author")))
    ]
    last_review = automated_reviews[-1] if automated_reviews else None
    reviewed_at = (last_review.get("submittedAt") or "") if last_review else ""

    commits_after = []
    if reviewed_at:
        reviewed_time = parse_time(reviewed_at)
        for commit in commits:
            if commit["parents"]["totalCount"] != 1:
                continue
            if parse_time(commit["authoredDate"]) > reviewed_time:
                commits_after.append(
                    "%s %s" % (commit["oid"][:7], commit["messageHeadline"])
                )

    requested = [
        node["requestedReviewer"]
        for node in pr["reviewRequests"]["nodes"]
        if node.get("requestedReviewer") is not None
    ]
    automated_requested = any(is_automated(r.get("login")) for r in requested)
    human_requested = [
        r.get("login") or r.get("slug")
        for r in requested
        if not is_automated(r.get("login"))
    ]

    threads = _open_threads(pr)
    awaiting = [t for t in threads if t["lastAuthor"] != me]
    hints = dependency_hints(pr.get("body"))

    if head is not None:
        elapsed = (now - parse_time(head["committedDate"])).total_seconds()
    else:
        elapsed = 0
    minutes = int(elapsed // 60)

    on_head = False
    if last_review is not None:
        commit = last_review.get("commit") or {}
        on_head = commit.get("oid") == pr["headRefOid"]

    return {
        "url": pr["url"],
        "number": pr["number"],
        "title": pr["title"],
        "isDraft": pr["isDraft"],
        "state": pr["state"],
        "mergeable": pr.get("mergeable"),
        "base": pr["baseRefName"],
        "headRef": pr["headRefName"],
        "head": pr["headRefOid"],
        "labels": labels,
        "ci": ci,
        "minutesSinceHead": minutes,
        "automatedReviewAt": last_review.get("submittedAt") if last_review else None,
        "automatedReviewOnHead": on_head,
        "automatedReviewRequested": automated_requested,
        "commitsAfterReview": commits_after,
        "humanReviewersRequested": human_requested,
        "threadsAwaitingMe": len(awaiting),
        "humanThreadsAwaitingMe": sum(1 for t in awaiting if not t["automated"]),
        "openThreads": threads,
        "dependencyHints": hints,
        "bucket": _bucket(
            labels, hints, pr.get("mergeable"), automated_requested, minutes,
            ci, awaiting, last_review is not None, commits_after,
        ),
    }


def run_gh(args):
    """Run ``gh`` with stdin closed and return its stdout; raises on failure."""
    result = subprocess.run(
        ["gh"] + list(args),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT,
        check=True,
    )
    return result.stdout


def fetch_pr(owner, name, number):
    args = [
        "api", "graphql",
        "-f", "query=" + QUERY,
        "-F", "owner=" + owner,
        "-F", "name=" + name,
        "-F", "number=" + str(number),
    ]
    pr = json.loads(run_gh(args))["data"]["repository"]["pullRequest"]
    if pr is not None and pr.get("mergeable") == "UNKNOWN":
        sleep(UNKNOWN_RETRY_DELAY)
        pr = json.loads(run_gh(args))["data"]["repository"]["pullRequest"]
    if pr is None:
        raise ValueError("pull request %s/%s#%s not found" % (owner, name, number))
    return pr


def search_targets():
    output = run_gh([
        "search", "prs", "--draft", "--state", "open", "--author", "@me",
        "--json", "repository,number", "--limit", "100",
    ])
    targets = []
    for row in json.loads(output):
        owner, name = row["repository"]["nameWithOwner"].split("/", 1)
        targets.append((owner, name, str(row["number"])))
    targets.sort()
    return targets


def _describe(exc):
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or "").strip() or "exit status %s" % exc.returncode
        text = "gh failed: %s" % detail
    elif isinstance(exc, subprocess.TimeoutExpired):
        text = "gh timed out after %s seconds" % exc.timeout
    else:
        text = "%s: %s" % (type(exc).__name__, exc)
    return text[:ERROR_LIMIT]


def _emit(record):
    sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
    sys.stdout.flush()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        me = run_gh(["api", "user", "--jq", ".login"]).strip()
    except (subprocess.SubprocessError, OSError) as exc:
        sys.stderr.write("pr_status: cannot determine GitHub login: %s\n" % _describe(exc))
        return 1
    now = datetime.now(timezone.utc)

    if argv:
        targets = []
        for value in argv:
            match = TARGET_RE.fullmatch(value)
            if not match:
                sys.stderr.write(
                    "pr_status: expected owner/repo#N, got %r\n" % (value,)
                )
                return 1
            targets.append(match.groups())
    else:
        try:
            targets = search_targets()
        except (subprocess.SubprocessError, OSError, ValueError, KeyError,
                TypeError, AttributeError) as exc:
            sys.stderr.write("pr_status: draft PR search failed: %s\n" % _describe(exc))
            return 1

    failed = False
    for owner, name, number in targets:
        repo = "%s/%s" % (owner, name)
        try:
            record = classify(fetch_pr(owner, name, number), me, now)
        except (subprocess.SubprocessError, OSError, KeyError, TypeError,
                ValueError, AttributeError, IndexError) as exc:
            failed = True
            record = {
                "bucket": "error",
                "error": _describe(exc),
                "url": "https://github.com/%s/pull/%s" % (repo, number),
            }
        record["repo"] = repo
        _emit(record)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

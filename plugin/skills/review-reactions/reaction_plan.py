#!/usr/bin/env python3
"""Dry-run plan of status reactions for the user's review-request chat posts.

Usage:
    reaction_plan.py MESSAGES_JSON --user-id ID [--seconds N] [--now EPOCH]
                     [--author-login LOGIN] [--merged LIST] [--approved LIST]
                     [--feedback LIST]

MESSAGES_JSON is a JSON array of chat messages (or an object with a
``messages`` array). For each of the user's posts inside the window that link
GitHub pull requests, the helper reads the PRs with ``gh pr view`` and decides
which reactions the post needs (feedback, approved, merged) and which are
missing. It prints ``{"rows": [...], "calls": [...]}``; it never contacts the
chat service and never adds reactions itself.
"""

import argparse
import json
import re
import subprocess
import sys
import time

GH_TIMEOUT = 30
DEFAULT_SECONDS = 7 * 24 * 60 * 60
ERROR_MESSAGE_LIMIT = 120

ROLES = ("feedback", "approved", "merged")
DEFAULT_REACTIONS = {
    "feedback": ("speech_balloon", "comment"),
    "approved": ("white_check_mark",),
    "merged": ("twisted_rightwards_arrows", "merge", "merged"),
}

USER_ID_RE = re.compile(r"[UW][A-Z0-9]+")
EMOJI_RE = re.compile(r"[a-z0-9_+'-]+")
PR_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/pull/([0-9]+)")

AUTOMATED_LOGINS = frozenset(
    {
        "github-advanced-security",
        "copilot-swe-agent",
        "github-actions",
        "copilot-pull-request-reviewer",
    }
)

FEEDBACK_STATES = ("COMMENTED", "CHANGES_REQUESTED")

PR_JQ = (
    "{state: .state, reviewDecision: .reviewDecision, author: .author.login, "
    "reviews: [.reviews[] | {state: .state, login: .author.login}]}"
)


def is_automated(login):
    if not login:
        return False
    return (
        "copilot" in login.lower()
        or login.endswith("[bot]")
        or login in AUTOMATED_LOGINS
    )


def parse_emoji_list(text):
    """Parse ``a, :b:`` into ``("a", "b")``; raises ValueError when invalid."""
    names = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        names.append(item.strip(":"))
    if not names:
        raise ValueError("emoji list is empty")
    for name in names:
        if not EMOJI_RE.fullmatch(name):
            raise ValueError("invalid emoji name %r" % (name,))
    return tuple(names)


def fetch_pr_status(url):
    """Read one PR's state, review decision, author and reviews through gh."""
    result = subprocess.run(
        ["gh", "pr", "view", url, "--json", "state,reviewDecision,author,reviews",
         "--jq", PR_JQ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT,
        check=True,
    )
    return json.loads(result.stdout)


def pr_links(text):
    links = []
    for match in PR_URL_RE.finditer(text or ""):
        url = "https://github.com/%s/%s/pull/%s" % match.groups()
        if url not in links:
            links.append(url)
    return links


def reaction_names(message):
    names = []
    for item in message.get("reactions") or []:
        if isinstance(item, str):
            name = item
        else:
            name = item.get("name") or ""
        names.append(name.split("::", 1)[0])
    return names


def _ts_value(ts):
    if ts is None:
        return 0.0
    return float(ts)


def candidates(messages, user_id, cutoff):
    """The user's in-window posts that link PRs, newest first."""
    selected = []
    for message in messages:
        if message.get("user") != user_id:
            continue
        try:
            ts = _ts_value(message.get("ts"))
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        links = pr_links(message.get("text") or "")
        if links:
            selected.append((ts, message, links))
    selected.sort(key=lambda item: -item[0])
    return [(message, links) for _, message, links in selected]


def _status_label(statuses, needed):
    states = [status.get("state") for status in statuses]
    if all(state == "MERGED" for state in states):
        return "Merged"
    if any(state == "CLOSED" for state in states):
        return "Closed (check)"
    if "approved" in needed:
        return "Approved"
    if "feedback" in needed:
        return "Has feedback"
    if any(state == "MERGED" for state in states):
        return "Partly merged"
    return "Awaiting review"


def _has_outside_feedback(statuses, author):
    for status in statuses:
        for review in status.get("reviews") or []:
            if review.get("state") not in FEEDBACK_STATES:
                continue
            login = review.get("login")
            if login is None:
                return True
            if login != author and not is_automated(login):
                return True
    return False


def plan(messages, user_id, cutoff, fetch=None, author_login=None, reactions=None):
    """Build ``{"rows": [...], "calls": [...]}`` for the candidate posts."""
    if fetch is None:
        fetch = fetch_pr_status
    names = dict(DEFAULT_REACTIONS)
    for role, override in (reactions or {}).items():
        if role not in names:
            raise ValueError("unknown reaction role %r" % (role,))
        names[role] = tuple(override)

    rows = []
    calls = []
    for message, links in candidates(messages, user_id, cutoff):
        ts = message.get("ts")
        statuses = []
        errors = []
        for url in links:
            try:
                statuses.append(fetch(url))
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                errors.append("%s: %s" % (url, str(exc)[:ERROR_MESSAGE_LIMIT]))
        if errors:
            rows.append({
                "ts": ts,
                "prs": links,
                "status": "Error",
                "reactions": [],
                "action": "Skipped (PR read failed)",
                "errors": errors,
            })
            continue

        author = author_login or statuses[0].get("author")
        needed = []
        if _has_outside_feedback(statuses, author):
            needed.append("feedback")
        if all(status.get("reviewDecision") == "APPROVED" for status in statuses):
            needed.append("approved")
        if all(status.get("state") == "MERGED" for status in statuses):
            needed.append("merged")

        existing = set(reaction_names(message))
        missing = [
            names[role][0] for role in needed
            if not existing.intersection(names[role])
        ]
        if not needed:
            action = "No reaction needed"
        elif not missing:
            action = "Already present"
        else:
            action = "Pending"

        rows.append({
            "ts": ts,
            "prs": links,
            "status": _status_label(statuses, needed),
            "reactions": [names[role][0] for role in needed],
            "missing": missing,
            "action": action,
        })
        calls.extend({"ts": ts, "emoji": name} for name in missing)
    return {"rows": rows, "calls": calls}


def load_messages(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return data.get("messages") or []
    return data


def _user_id(value):
    if not USER_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "%r is not a chat user ID; pass the member ID (U... or W...), "
            "not a channel or DM ID" % (value,)
        )
    return value


def _emoji_list(value):
    try:
        return parse_emoji_list(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "%s (use comma-separated lowercase names such as eyes,ok)" % exc
        )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="reaction_plan.py",
        description="Plan status reactions for review-request posts (dry run).",
    )
    parser.add_argument("messages_json", metavar="MESSAGES_JSON")
    parser.add_argument("--user-id", required=True, type=_user_id)
    parser.add_argument("--author-login", default=None)
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    parser.add_argument("--now", type=float, default=None)
    for role in ROLES:
        parser.add_argument("--" + role, type=_emoji_list, default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    now = args.now if args.now else time.time()
    cutoff = now - args.seconds
    overrides = {
        role: getattr(args, role)
        for role in ROLES
        if getattr(args, role) is not None
    }
    result = plan(
        load_messages(args.messages_json),
        args.user_id,
        cutoff,
        author_login=args.author_login or None,
        reactions=overrides,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Inventory and bump pinned references to shared GitHub workflow repositories.

Usage:
    shared_refs.py scan    [--root DIR] --repo OWNER/REPO [--repo ...]
    shared_refs.py latest  --repo OWNER/REPO [--repo ...]
    shared_refs.py update  [--root DIR] --repo OWNER/REPO --from OLD --to NEW
                           [--allow-major] [--write]

``scan`` lists every ``uses: OWNER/REPO[/path]@ref`` reference found in
``.github/workflows/*.y(a)ml`` and ``.github/actions/**/action.y(a)ml``.
``latest`` asks ``gh`` for each repository's tags and reports the newest
semantic version. ``update`` previews (or, with ``--write``, applies) a tag
bump for one repository; it refuses downgrades, non-semantic tags and, unless
``--allow-major`` is given, major-version changes. The helper never runs git.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

GH_TIMEOUT = 60

REPO_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
SEMVER_RE = re.compile(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)")
SUBPATH = r"(?:/[^@\s'\"]*)?"


def parse_semver(tag):
    """Return the (major, minor, patch) triple for a semantic tag, else None."""
    match = SEMVER_RE.fullmatch(tag)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def validate_repo(repo):
    if not REPO_RE.fullmatch(repo or ""):
        raise ValueError("invalid repository %r (expected OWNER/REPO)" % (repo,))


def examined_files(root):
    """Workflow and action files under ``<root>/.github`` in component order."""
    root = Path(root)
    github = root / ".github"
    found = set()
    workflows = github / "workflows"
    if workflows.is_dir():
        for pattern in ("*.yml", "*.yaml"):
            found.update(workflows.glob(pattern))
    actions = github / "actions"
    if actions.is_dir() and not actions.is_symlink():
        for name in ("action.yml", "action.yaml"):
            found.update(actions.rglob(name))
    files = [
        path for path in found
        if path.is_file() and not path.is_symlink()
    ]
    return sorted(files, key=lambda path: path.relative_to(root).parts)


def _relative(root, path):
    return path.relative_to(Path(root)).as_posix()


def _read(path):
    with open(path, "r", encoding="utf-8", newline=None) as handle:
        return handle.read()


def scan(root, repos):
    """Return every pinned reference to the given repositories."""
    for repo in repos:
        validate_repo(repo)
    patterns = [
        (repo, re.compile(
            r"uses:\s*['\"]?" + re.escape(repo) + r"(" + SUBPATH + r")@([^\s'\"#]+)"
        ))
        for repo in repos
    ]
    results = []
    for path in examined_files(root):
        relative = _relative(root, path)
        for number, line in enumerate(_read(path).splitlines(), start=1):
            for repo, pattern in patterns:
                for match in pattern.finditer(line):
                    ref = match.group(2)
                    results.append({
                        "file": relative,
                        "line": number,
                        "repo": repo,
                        "path": match.group(1).lstrip("/"),
                        "ref": ref,
                        "semver": parse_semver(ref) is not None,
                    })
    return results


def run_gh(args):
    result = subprocess.run(
        ["gh"] + list(args),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT,
        check=True,
    )
    return result.stdout


def newest_tag(tags):
    best = None
    for tag in tags:
        version = parse_semver(tag)
        if version is None:
            continue
        key = (version, tag)
        if best is None or key > best:
            best = key
    return best[1] if best else None


def latest(repos):
    """Map each repository (first occurrence order) to its newest semver tag."""
    result = {}
    for repo in repos:
        validate_repo(repo)
        if repo in result:
            continue
        output = run_gh(["api", "--paginate", "repos/%s/tags" % repo, "--jq", ".[].name"])
        result[repo] = newest_tag(output.split())
    return result


def update(root, repo, old, new, allow_major=False, write=False):
    """Replace ``repo@old`` with ``repo@new``; returns per-file change counts."""
    validate_repo(repo)
    old_version = parse_semver(old)
    new_version = parse_semver(new)
    if old_version is None or new_version is None:
        raise ValueError("both --from and --to must be semantic versions like v1.2.3")
    if new_version <= old_version:
        raise ValueError("new version %s is not newer than %s" % (new, old))
    if new_version[0] != old_version[0] and not allow_major:
        raise ValueError(
            "%s -> %s changes the major version; pass --allow-major after review"
            % (old, new)
        )
    pattern = re.compile(
        r"(uses:\s*['\"]?" + re.escape(repo) + SUBPATH + r"@)"
        + re.escape(old) + r"(?=\Z|[\s'\"#])"
    )
    changes = []
    for path in examined_files(root):
        text = _read(path)
        updated, count = pattern.subn(lambda m: m.group(1) + new, text)
        if not count:
            continue
        changes.append({"file": _relative(root, path), "references": count})
        if write:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(updated)
    return changes


def build_parser():
    parser = argparse.ArgumentParser(
        prog="shared_refs.py",
        description="Inventory and bump pinned shared workflow references.",
    )
    sub = parser.add_subparsers(dest="command", metavar="{scan,latest,update}")
    sub.required = True

    p_scan = sub.add_parser("scan", help="list pinned references")
    p_scan.add_argument("--root", default=".")
    p_scan.add_argument("--repo", action="append", default=[])

    p_latest = sub.add_parser("latest", help="newest semantic tag per repository")
    p_latest.add_argument("--repo", action="append", default=[])

    p_update = sub.add_parser("update", help="preview or apply a tag bump")
    p_update.add_argument("--root", default=".")
    p_update.add_argument("--repo", required=True)
    p_update.add_argument("--from", dest="old", required=True)
    p_update.add_argument("--to", dest="new", required=True)
    p_update.add_argument("--allow-major", action="store_true")
    p_update.add_argument("--write", action="store_true")
    return parser


def _fail(message, code):
    sys.stderr.write("shared_refs: %s\n" % message)
    return code


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command in ("scan", "latest"):
        if not args.repo:
            return _fail("give at least one --repo OWNER/REPO", 1)
        for repo in args.repo:
            if not REPO_RE.fullmatch(repo):
                return _fail("invalid repository %r (expected OWNER/REPO)" % repo, 1)
        if args.command == "scan":
            print(json.dumps(scan(args.root, args.repo), indent=2))
            return 0
        try:
            result = latest(args.repo)
        except (subprocess.SubprocessError, OSError) as exc:
            return _fail("listing tags failed: %s" % exc, 1)
        print(json.dumps(result, indent=2))
        return 0

    if not REPO_RE.fullmatch(args.repo):
        return _fail("invalid repository %r (expected OWNER/REPO)" % args.repo, 1)
    try:
        changes = update(
            args.root, args.repo, args.old, args.new,
            allow_major=args.allow_major, write=args.write,
        )
    except ValueError as exc:
        return _fail(str(exc), 2)
    print(json.dumps({"write": args.write, "changes": changes}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

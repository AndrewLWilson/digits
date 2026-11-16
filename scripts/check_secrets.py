#!/usr/bin/env python3
"""Secret guard: offline detect-secrets scan of the repository tree.

Verifies that the Git index matches the working tree, then runs the pinned
``detect-secrets`` scanner without network verification and reports only the
path, line number and detector type of each finding.

Run as ``python scripts/check_secrets.py``.
"""

import json
import subprocess
import sys
from pathlib import Path

try:
    from scripts import check_repository as _repository_guard
except ImportError:  # executed directly: the scripts directory is on sys.path
    import check_repository as _repository_guard

ROOT = Path(__file__).resolve().parent.parent

SCANNER = "detect-secrets"
EXCLUDE_FILES = r"(^|/)(\.git|\.venv|__pycache__|node_modules)(/|$)"

def require_index_match(root):
    """Delegate to the repository guard's index check (shared contract)."""
    return _repository_guard.require_index_match(root)


def scanner_command():
    return [
        SCANNER,
        "scan",
        "--no-verify",
        "--all-files",
        "--exclude-files",
        EXCLUDE_FILES,
    ]


def main():
    try:
        require_index_match(ROOT)
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    try:
        result = subprocess.run(
            scanner_command(),
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print(
            "detect-secrets is missing; install it from requirements-dev.txt "
            "in an isolated virtual environment, then rerun.",
            file=sys.stderr,
        )
        return 1
    except OSError:
        print(
            "The secret scanner could not be started; no passing result is "
            "claimed.",
            file=sys.stderr,
        )
        return 1

    if result.returncode != 0:
        print(
            "The secret scanner failed (exit status {}); no passing result is "
            "claimed.".format(result.returncode),
            file=sys.stderr,
        )
        return 1

    try:
        results = json.loads(result.stdout)["results"]
        findings = [
            (path, finding["line_number"], finding["type"])
            for path, entries in results.items()
            for finding in entries
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        print(
            "The secret scanner produced unreadable output; no passing result "
            "is claimed.",
            file=sys.stderr,
        )
        return 1

    if findings:
        for path, line_number, kind in findings:
            print("{}:{}: {}".format(path, line_number, kind), file=sys.stderr)
        return 1

    print("Secret scan passed; manual review is still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

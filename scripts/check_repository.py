#!/usr/bin/env python3
"""Repository guard: structure, path, JSON and private-term checks.

Inspects every file that would be part of a source snapshot (tracked files
plus untracked files that are not ignored) and rejects private or runtime
artifacts, machine-specific home paths, malformed JSON, symlinks, files that
are not UTF-8 text, a missing root README and, optionally, terms listed in a
local private-terms file.

Run as ``python scripts/check_repository.py``.
"""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRIVATE_TERMS_ENV = "DIGITS_PRIVATE_TERMS"
DEFAULT_PRIVATE_TERMS = ".config/digits/private-terms.txt"

PRIVATE_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        "fish_variables",
        "mcp-config.json",
        "permissions-config.json",
        "profiles.yaml",
        "profiles.yml",
    }
)
PRIVATE_SUFFIXES = frozenset(
    {
        ".bak",
        ".db",
        ".key",
        ".log",
        ".mp4",
        ".p12",
        ".pem",
        ".pfx",
        ".png",
        ".sqlite",
        ".sqlite3",
        ".vsix",
        ".xlsx",
        ".zip",
    }
)
PRIVATE_DIRECTORIES = frozenset(
    {
        ".local",
        "logs",
        "mcp-oauth-config",
        "node_modules",
        "restart",
        "resurrect",
        "session-state",
        "sidebar-sessions-state",
    }
)
BACKUP_MARKER = re.compile(r"\.(bak|backup)([-.]|$)")
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/")

SYMLINK_MESSAGE = "symlinks are not accepted in a source snapshot"
ARTIFACT_MESSAGE = "private, generated, or binary artifact is not allowed"
UTF8_MESSAGE = "file must be readable UTF-8 source"
HOME_PATH_MESSAGE = "hardcoded user home path"
README_FAILURE = "README.md: missing project README"


class IndexMismatchError(ValueError):
    """The Git index and the working tree hold different content."""


class IndexComparisonError(RuntimeError):
    """Git could not compare the index with the working tree."""


class TermsConfigurationError(ValueError):
    """The private-terms file could not be located or loaded."""


def require_index_match(root):
    """Raise unless tracked files in the working tree equal the index."""
    command = ["git", "diff", "--quiet", "--no-ext-diff", "--no-textconv", "--"]
    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise IndexComparisonError(
            "Could not compare the Git index with the working tree; "
            "checks stopped. ({})".format(error.strerror or error)
        ) from None
    if result.returncode == 0:
        return
    if result.returncode == 1:
        raise IndexMismatchError(
            "Staged files differ from the working tree; inspect `git diff` "
            "and stage what you mean to commit, then rerun the checks."
        )
    raise IndexComparisonError(
        "Could not compare the Git index with the working tree; checks stopped."
    )


def final_suffix(name):
    """Return the text from the last dot of ``name``, or '' when none.

    A name whose only dot is its first character (``.pem``) has no suffix.
    """
    index = name.rfind(".")
    if index <= 0:
        return ""
    return name[index:]


def is_private_artifact(relative_path):
    parts = [part for part in relative_path.split("/") if part]
    if not parts:
        return False
    name = parts[-1]
    if name in PRIVATE_NAMES or name.startswith(".env."):
        return True
    if final_suffix(name) in PRIVATE_SUFFIXES:
        return True
    if any(part in PRIVATE_DIRECTORIES for part in parts):
        return True
    return BACKUP_MARKER.search(name) is not None


def read_text(path):
    """Read ``path`` strictly as UTF-8; raise OSError or UnicodeDecodeError."""
    with open(str(path), "rb") as handle:
        data = handle.read()
    return data.decode("utf-8")


def json_error_line(text):
    """Return the 1-based line of the first JSON error, or None if valid."""
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        return error.lineno
    except (ValueError, RecursionError):
        return 1
    return None


def inspect_file(relative_path):
    """Return a list of error strings for one path relative to ``ROOT``."""
    relative = str(relative_path)
    path = Path(ROOT) / relative
    if os.path.islink(str(path)):
        return ["{}: {}".format(relative, SYMLINK_MESSAGE)]

    errors = []
    if is_private_artifact(relative):
        errors.append("{}: {}".format(relative, ARTIFACT_MESSAGE))

    try:
        text = read_text(path)
    except (OSError, UnicodeDecodeError):
        errors.append("{}: {}".format(relative, UTF8_MESSAGE))
        return errors

    if HOME_PATH.search(text):
        errors.append("{}: {}".format(relative, HOME_PATH_MESSAGE))

    if final_suffix(path.name) == ".json":
        line = json_error_line(text)
        if line is not None:
            errors.append("{}: invalid JSON at line {}".format(relative, line))
    return errors


def list_files():
    """Return sorted relative paths of tracked and non-ignored untracked files."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    output = result.stdout.decode("utf-8", errors="surrogateescape")
    return sorted({entry for entry in output.split("\0") if entry})


def resolve_terms_file():
    """Return the private-terms file to use, or None when the guard is skipped."""
    configured = os.environ.get(PRIVATE_TERMS_ENV, "")
    if configured:
        path = Path(os.path.expanduser(configured))
        if not path.is_file():
            raise TermsConfigurationError(
                "{} does not point to a readable file: {}".format(
                    PRIVATE_TERMS_ENV, path
                )
            )
        return path
    default = Path(os.path.expanduser("~")) / DEFAULT_PRIVATE_TERMS
    if not os.path.lexists(str(default)):
        return None
    return default


def load_terms(path):
    """Return [(terms-file line number, case-folded term)] read from ``path``."""
    try:
        text = read_text(path)
    except UnicodeDecodeError:
        raise TermsConfigurationError(
            "The private-terms file {} is not valid UTF-8.".format(path)
        ) from None
    except OSError as error:
        raise TermsConfigurationError(
            "Could not read the private-terms file {}: {}".format(
                path, error.strerror or "unreadable"
            )
        ) from None
    terms = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        terms.append((number, stripped.casefold()))
    return terms


def scan_private_terms(relative_path, terms):
    """Return findings that name only the location and the term number."""
    try:
        text = read_text(Path(ROOT) / relative_path)
    except (OSError, UnicodeDecodeError):
        return []
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        folded = line.casefold()
        for term_number, term in terms:
            if term in folded:
                findings.append(
                    "{}:{}: private term #{}".format(
                        relative_path, line_number, term_number
                    )
                )
    return findings


def has_root_readme():
    try:
        mode = os.lstat(str(Path(ROOT) / "README.md")).st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode)


def main():
    try:
        require_index_match(ROOT)
    except (IndexMismatchError, IndexComparisonError) as error:
        print(error, file=sys.stderr)
        return 1

    try:
        terms_file = resolve_terms_file()
        terms = load_terms(terms_file) if terms_file is not None else []
    except TermsConfigurationError as error:
        print(error, file=sys.stderr)
        return 1

    files = list_files()
    failures = []
    for relative in files:
        failures.extend(inspect_file(relative))
        if terms and not os.path.islink(str(Path(ROOT) / relative)):
            failures.extend(scan_private_terms(relative, terms))

    if not has_root_readme():
        failures.append(README_FAILURE)

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    if terms_file is None:
        outcome = "private-terms guard skipped (no terms file)"
    else:
        outcome = "private-terms guard checked {} terms".format(len(terms))
    print(
        "Repository structure/JSON/path checks passed ({} files); {}.".format(
            len(files), outcome
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Private reviewed-through cursor for /digits:self-improve.

This helper only guards the checkpoint state. It never collects chat history,
applies edits, posts anything, starts agents or creates schedules. The agent
running the skill does the review; this file records which window was reviewed,
binds the approved proposal by hash, and advances the cursor only after a
verified, fully approved run.

State: ~/.local/state/digits/self-improve/state.json (mode 0600).
"""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from pathlib import Path

STATE = Path(".local/state/digits/self-improve/state.json")
PRIVATE_CONTEXT = Path(".config/digits/context")
ENVIRONMENTS = frozenset(
    {
        "left_pinky",
        "left_ring",
        "left_middle",
        "left_pointer",
        "left_thumb",
        "right_thumb",
        "right_pointer",
        "right_middle",
        "right_ring",
        "right_pinky",
    }
)
OVERLAP = datetime.timedelta(hours=24)
CLOUD_STATES = ("complete", "lagging", "unavailable")
RUN_ID = re.compile(r"[0-9a-f]{32}")


# Time ------------------------------------------------------------------------


def timestamp(text):
    if not isinstance(text, str):
        raise ValueError("Timestamp must be an ISO 8601 string with a UTC offset.")
    value = text.strip()
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Unreadable timestamp {text!r}; use ISO 8601 with a UTC offset.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timestamp {text!r} has no UTC offset; add Z or +00:00.")
    return parsed.astimezone(datetime.timezone.utc)


def iso(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


# Paths and artifacts ----------------------------------------------------------


def safe_path(path):
    absolute = Path(os.path.normpath(os.path.abspath(os.fspath(path))))
    parts = absolute.parts
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Refusing a symlink in the path: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"Parent is not a directory: {current}")
    return absolute


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def artifact(path):
    if not isinstance(path, (str, os.PathLike)):
        raise ValueError("Missing evidence: an artifact path must be a string.")
    expanded = Path(os.path.expanduser(os.fspath(path)))
    if not expanded.is_absolute():
        raise ValueError(f"Artifact path must be absolute: {path}")
    checked = safe_path(expanded)
    try:
        info = os.lstat(checked)
    except FileNotFoundError:
        raise ValueError(f"Missing evidence: {checked} does not exist.") from None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Missing evidence: {checked} is not a regular file.")
    return {"path": str(checked), "sha256": sha256_bytes(checked.read_bytes())}


def unchanged(record):
    current = artifact(record["path"])
    if current["sha256"] != record["sha256"]:
        raise ValueError(f"{record['path']} changed after approval; renewed approval required.")
    return current


def load_json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from None


# State -------------------------------------------------------------------------


def state_path(home):
    return Path(home) / STATE


def cursor_text(state):
    success = state.get("last_success")
    if success:
        return success["reviewed_through"]
    return state["baseline"]["reviewed_through"]


def read_state(home):
    path = safe_path(state_path(home))
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError(f"{path} must be a private regular file with mode 0600.")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError(f"{path} is unrecognized; it was left untouched (do not reset it).") from None
    if not isinstance(state, dict) or state.get("format") != 1:
        raise ValueError(f"{path} has an unrecognized format; it was left untouched (do not reset it).")
    baseline = timestamp(state["baseline"]["reviewed_through"])
    success = state.get("last_success")
    if success and timestamp(success["reviewed_through"]) < baseline:
        raise ValueError("The last success is earlier than the baseline; state is inconsistent.")
    active = state.get("active")
    if active:
        if not isinstance(active.get("run_id"), str) or not RUN_ID.fullmatch(active["run_id"]):
            raise ValueError("The active run has an invalid run_id.")
        cursor = cursor_text(state)
        if active.get("reviewed_since") != cursor:
            raise ValueError("The active run's reviewed_since does not match the success cursor.")
        if not timestamp(active["query_since"]) <= timestamp(cursor) < timestamp(active["reviewed_through"]):
            raise ValueError("The active run's window is inconsistent with the success cursor.")
    return state


def ensure_state_dir(home):
    home = safe_path(home)
    target = safe_path(state_path(home).parent)
    current = home
    for part in target.relative_to(home).parts:
        current = current / part
        safe_path(current)
        if not current.exists():
            os.mkdir(current, 0o700)
            os.chmod(current, 0o700)
    return target


def save(home, value):
    directory = ensure_state_dir(home)
    final = safe_path(state_path(home))
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=str(directory))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


@contextlib.contextmanager
def locked(home):
    checked = safe_path(home)
    descriptor = os.open(checked, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


# Context verification ------------------------------------------------------------


def _load_installer(harness):
    module_path = harness / "context_install.py"
    spec = importlib.util.spec_from_file_location("digits_checkpoint_context_install", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    entry = str(harness)
    sys.path.insert(0, entry)
    try:
        spec.loader.exec_module(module)
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(entry)
    return module


def _verify_owned_fallback(installer, home, receipt):
    """Ownership check from the installer contract, used if it has no helper."""
    resolve = getattr(installer, "checked_path", None) or (lambda base, rel: safe_path(Path(base) / rel))
    for relative, record in receipt.get("files", {}).items():
        path = resolve(home, relative)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            raise ValueError(f"Installed context file is missing or modified: {path}") from None
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != record.get("mode")
            or sha256_bytes(Path(path).read_bytes()) != record.get("sha256")
        ):
            raise ValueError(f"Installed context file was modified: {path}")
    for relative in receipt.get("directories", []):
        if not Path(resolve(home, relative)).is_dir():
            raise ValueError(f"Installed context directory changed: {relative}")


def verify_context(home, harness_root):
    harness = safe_path(harness_root)
    if not (harness / "context_install.py").is_file() or not (harness / "context" / "bootstrap.md").is_file():
        raise ValueError(
            f"{harness} is not a Digits source checkout (needs context_install.py and context/bootstrap.md); "
            "use the verified source repository, not a plugin-only cache."
        )
    installer = _load_installer(harness)
    home = Path(home)
    receipt = installer.read_receipt(home)
    if receipt is None:
        raise ValueError("There is no owned installed context receipt; install the context first.")
    verifier = getattr(installer, "verify_owned", None)
    if verifier is not None:
        verifier(home, receipt)
    else:
        _verify_owned_fallback(installer, home, receipt)
    if installer.make_plan(home)["writes"]:
        raise ValueError("Source and live context differ; preview and apply the context installer first.")
    return artifact(home / installer.ENTRY)


# Validation ---------------------------------------------------------------------------


def require_run(state, run_id):
    active = state.get("active") if state else None
    if not active or active.get("run_id") != run_id:
        raise ValueError(f"Wrong or inactive run id {run_id!r}; no cursor was changed.")
    return active


def _count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"coverage.{name} must be a non-negative integer.")


def validate_proposal(proposal, run):
    if not isinstance(proposal, dict):
        raise ValueError("The proposal must be a JSON object.")
    for key in ("run_id", "reviewed_since", "reviewed_through"):
        if proposal.get(key) != run[key]:
            raise ValueError(f"Proposal {key} does not match the frozen run window.")
    coverage = proposal.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("Incomplete coverage: the proposal has no coverage object.")
    environments = coverage.get("environments")
    if (
        not isinstance(environments, list)
        or len(environments) != len(ENVIRONMENTS)
        or set(environments) != ENVIRONMENTS
    ):
        raise ValueError("Incomplete coverage: environments must list all ten roots exactly once.")
    if coverage.get("local") != "complete":
        raise ValueError("Incomplete coverage: local history must be complete.")
    if coverage.get("cloud") not in CLOUD_STATES:
        raise ValueError("Incomplete coverage: cloud must be complete, lagging or unavailable.")
    if coverage.get("material_gaps") != []:
        raise ValueError("Incomplete coverage: material gaps remain.")
    _count(coverage.get("sessions_considered"), "sessions_considered")
    _count(coverage.get("turns_considered"), "turns_considered")
    if not isinstance(proposal.get("changes"), list):
        raise ValueError("Proposal changes must be a list.")


def _strictly_inside(path, root):
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative.parts != ()


def change_states(proposal, run, home):
    roots = [safe_path(run["harness_root"]), safe_path(Path(home) / PRIVATE_CONTEXT)]
    seen = set()
    states = []
    for change in proposal["changes"]:
        if not isinstance(change, dict):
            raise ValueError("Each change must be an object.")
        raw = change.get("path")
        summary = change.get("summary")
        if not isinstance(raw, str) or not isinstance(summary, str) or not summary.strip():
            raise ValueError("Each change needs a string path and a non-empty summary.")
        expanded = Path(os.path.expanduser(raw))
        if not expanded.is_absolute():
            raise ValueError(f"Change path must be absolute: {raw}")
        path = safe_path(expanded)
        if not any(_strictly_inside(path, root) for root in roots):
            raise ValueError(f"Change path {path} is outside the harness and the private context directory.")
        if path in seen:
            raise ValueError(f"Duplicate change path: {path}")
        seen.add(path)
        if os.path.lexists(path):
            if not stat.S_ISREG(os.lstat(path).st_mode):
                raise ValueError(f"Change path is not a regular file: {path}")
            digest = sha256_bytes(path.read_bytes())
        else:
            digest = None
        states.append({"path": str(path), "sha256": digest})
    return states


def _load_proposal(path_record):
    proposal = load_json_file(path_record["path"])
    if not isinstance(proposal, dict):
        raise ValueError("The proposal must be a JSON object.")
    return proposal


# Operations ---------------------------------------------------------------------------


def _initialize(state, home, now, since, evidence):
    if state is not None:
        raise ValueError("The checkpoint is already initialized.")
    boundary = timestamp(since)
    if boundary > now:
        raise ValueError("The baseline boundary lies in the future.")
    return {
        "format": 1,
        "baseline": {"reviewed_through": iso(boundary), "evidence": artifact(evidence)},
        "active": None,
        "last_success": None,
    }


def _begin(state, home, now, owner, harness_root):
    if state is None:
        raise ValueError("Initialize the checkpoint first (initialize --since ... --evidence ...).")
    if state.get("active"):
        raise ValueError(f"A run is already active (run {state['active']['run_id']}).")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("The owner session id must not be blank.")
    installed = verify_context(home, harness_root)
    cursor = timestamp(cursor_text(state))
    if now <= cursor:
        raise ValueError("No forward window: the current time is not after the success cursor.")
    baseline = timestamp(state["baseline"]["reviewed_through"])
    state["active"] = {
        "run_id": uuid.uuid4().hex,
        "owner": owner.strip(),
        "harness_root": str(safe_path(harness_root)),
        "reviewed_since": cursor_text(state),
        "reviewed_through": iso(now),
        "query_since": iso(max(baseline, cursor - OVERLAP)),
        "installed_before": installed,
        "approval": None,
    }
    return state


def _approve(state, home, now, run_id, proposal, approval_ref):
    run = require_run(state, run_id)
    record = artifact(proposal)
    body = _load_proposal(record)
    validate_proposal(body, run)
    if not isinstance(approval_ref, str) or not approval_ref.strip():
        raise ValueError("The approval reference must not be blank.")
    report = artifact(body.get("readable_report"))
    before = change_states(body, run, home)
    run["approval"] = {
        "path": record["path"],
        "sha256": record["sha256"],
        "readable_report": report,
        "reference": approval_ref.strip(),
        "at": iso(now),
        "changes_before": before,
    }
    return state


def _check_report(report, run, approval, expected_outcome):
    if not isinstance(report, dict):
        raise ValueError("The completion report must be a JSON object that matches the run.")
    if report.get("run_id") != run["run_id"]:
        raise ValueError("The completion report run_id does not match the active run.")
    if report.get("proposal_sha256") != approval["sha256"]:
        raise ValueError("The completion report proposal_sha256 does not match the approved proposal.")
    if report.get("outcome") != expected_outcome:
        raise ValueError(f"The completion report outcome does not match the proposal (expected {expected_outcome}).")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("At least one check that passed is required.")
    for check in checks:
        if (
            not isinstance(check, dict)
            or check.get("result") != "passed"
            or not isinstance(check.get("command"), str)
            or not check["command"].strip()
            or not isinstance(check.get("evidence"), str)
            or not check["evidence"].strip()
        ):
            raise ValueError("Every check must have result passed, a command and evidence.")


def _finish(state, home, now, run_id, report):
    run = require_run(state, run_id)
    approval = run.get("approval")
    if not approval:
        raise ValueError("Explicit proposal approval is required before finish.")
    unchanged({"path": approval["path"], "sha256": approval["sha256"]})
    unchanged(approval["readable_report"])
    proposal = _load_proposal(approval)
    validate_proposal(proposal, run)
    report_record = artifact(report)
    completion = load_json_file(report_record["path"])
    expected = "updated" if proposal["changes"] else "no_change"
    _check_report(completion, run, approval, expected)
    before = approval["changes_before"]
    after = change_states(proposal, run, home)
    if [item["path"] for item in after] != [item["path"] for item in before] or any(
        new["sha256"] == old["sha256"] for new, old in zip(after, before)
    ):
        raise ValueError("Approved changes were not applied to every listed file.")
    installed = verify_context(home, run["harness_root"])
    state["last_success"] = {
        "run_id": run["run_id"],
        "owner": run["owner"],
        "reviewed_through": run["reviewed_through"],
        "completed_at": iso(now),
        "approval": approval,
        "report": report_record,
        "installed": installed,
        "outcome": expected,
    }
    state["active"] = None
    return state


def _abort(state, home, now, run_id):
    require_run(state, run_id)
    state["active"] = None
    return state


ACTIONS = {
    "initialize": _initialize,
    "begin": _begin,
    "approve": _approve,
    "finish": _finish,
    "abort": _abort,
}


def operate(home, action, now=None, **args):
    home = Path(home)
    now = utc_now() if now is None else now.astimezone(datetime.timezone.utc)
    if action == "status":
        state = read_state(home)
        return state if state is not None else {"initialized": False}
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}.")
    with locked(home):
        state = read_state(home)
        updated = ACTIONS[action](state, home, now, **args)
        save(home, updated)
        return updated


# CLI --------------------------------------------------------------------------------------


def parser():
    root = argparse.ArgumentParser(
        prog="checkpoint.py",
        description="Guard the private reviewed-through cursor of /digits:self-improve.",
    )
    root.add_argument("--home", default=None, help="home directory to use (default: your home; for isolated tests)")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show the checkpoint (read-only)")
    initialize = commands.add_parser("initialize", help="record the first reviewed-through baseline")
    initialize.add_argument("--since", required=True, help="UTC ISO 8601 boundary already reviewed")
    initialize.add_argument("--evidence", required=True, help="absolute path of the evidence artifact")
    begin = commands.add_parser("begin", help="reserve a run with a frozen review window")
    begin.add_argument("--owner", required=True, help="session id of the owning chat")
    begin.add_argument("--harness-root", required=True, help="absolute path of the Digits source checkout")
    approve = commands.add_parser("approve", help="bind an explicitly approved proposal")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--proposal", required=True, help="absolute path of proposal.json")
    approve.add_argument("--approval-ref", required=True, help="where the user approved (session/turn)")
    finish = commands.add_parser("finish", help="verify a completed run and advance the cursor")
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--report", required=True, help="absolute path of completion.json")
    abort = commands.add_parser("abort", help="release the active run without moving the cursor")
    abort.add_argument("--run-id", required=True)
    return root


def main(argv=None):
    options = parser().parse_args(argv)
    home = Path(os.path.abspath(os.path.expanduser(options.home))) if options.home else Path.home()
    arguments = {}
    if options.command == "initialize":
        arguments = {"since": options.since, "evidence": options.evidence}
    elif options.command == "begin":
        arguments = {"owner": options.owner, "harness_root": options.harness_root}
    elif options.command == "approve":
        arguments = {"run_id": options.run_id, "proposal": options.proposal, "approval_ref": options.approval_ref}
    elif options.command == "finish":
        arguments = {"run_id": options.run_id, "report": options.report}
    elif options.command == "abort":
        arguments = {"run_id": options.run_id}
    try:
        result = operate(home, options.command, **arguments)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        print(f"Self-improvement checkpoint: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

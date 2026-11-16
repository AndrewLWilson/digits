#!/usr/bin/env python3
"""Inspect Copilot chats in the ai-agents tmux session and deliver approved prompts.

Standard library only (Python 3.9+). Requires tmux, ps and lsof at run time.
Every function looks up module-level names at call time so tests can patch them.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HOME = Path.home()
COPILOT_DIR = (
    Path(os.environ["COPILOT_HOME"]).expanduser()
    if os.environ.get("COPILOT_HOME")
    else HOME / ".copilot"
)
STATE_ROOT = COPILOT_DIR / "session-state"
TMUX_SESSION = "ai-agents"
RELOAD_COMMAND = "/skills reload"
RELOAD_OPERATION = "reload-skills"
TMUX_PANE = os.environ.get("TMUX_PANE")
COMMAND_TIMEOUT = 15

ENVIRONMENTS = tuple(
    f"{hand}_{finger}"
    for hand in ("left", "right")
    for finger in ("thumb", "pointer", "middle", "ring", "pinky")
)
PANE_FIELDS = (
    "session_name",
    "pane_id",
    "pane_pid",
    "pane_current_path",
    "pane_current_command",
    "pane_title",
    "pane_in_mode",
    "pane_dead",
)
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_RE = re.compile(rf"^{UUID_PATTERN}$")
RESUMED_RE = re.compile(rf"\[INFO\] Resumed session: ({UUID_PATTERN})\s*$")
CHANGED_RE = re.compile(
    rf"\[INFO\] Session changed \(({UUID_PATTERN}) \u2192 ({UUID_PATTERN})\)"
)
DELIVERY_STATES = {"idle": {"idle"}, "submit": {"idle", "busy"}, "queue": {"busy"}}
CONFIRMED_STATUSES = {"received", "queued", "steering", "reloaded"}
DIGEST_KEYS = ("version", "recipient", "message", "message_sha256", "operation", "delivery")
NO_COMPOSER_NOTICE = "(no Copilot composer was recognized on this screen)"
RELOAD_SUCCESS_RE = re.compile(
    r"\b(?:reloaded|loaded|refreshed)\b.{0,100}?\bskills?\b"
    r"|\bskills?\b.{0,100}?\b(?:reloaded|loaded|refreshed)\b",
    re.IGNORECASE,
)
RELOAD_FAILURE_RE = re.compile(
    r"\b(?:not\s+reloaded|not\s+loaded|could\s+not|cannot|unable|error|failed)\b",
    re.IGNORECASE,
)
POLL_INTERVAL = 0.2


class Refused(Exception):
    """Raised whenever the helper declines to act."""


def H(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def command(args, allowed=frozenset({0})):
    try:
        result = subprocess.run(
            list(args), capture_output=True, text=True, timeout=COMMAND_TIMEOUT
        )
    except FileNotFoundError:
        raise Refused(f"{args[0]} is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise Refused(f"{args[0]} did not finish within {COMMAND_TIMEOUT} seconds")
    if result.returncode not in allowed:
        raise Refused(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def logs_dir():
    return STATE_ROOT.parent / "logs"


def _same_path(a, b):
    a, b = Path(a), Path(b)
    return a == b or os.path.realpath(a) == os.path.realpath(b)


def environment_for(path):
    if not path:
        return None
    candidate = Path(os.path.normpath(str(path)))
    home = Path(os.path.normpath(str(HOME)))
    try:
        parts = candidate.relative_to(home).parts
    except ValueError:
        return None
    if parts and parts[0] in ENVIRONMENTS:
        return parts[0]
    return None


def discover():
    fmt = "\t".join("#{%s}" % field for field in PANE_FIELDS)
    output = command(["tmux", "list-panes", "-a", "-F", fmt])
    panes = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", len(PANE_FIELDS) - 1)
        if len(parts) != len(PANE_FIELDS):
            raise Refused("unrecognized tmux pane metadata")
        pane = dict(zip(PANE_FIELDS, parts))
        if pane["session_name"] != TMUX_SESSION:
            continue
        pane["environment"] = environment_for(pane["pane_current_path"])
        panes.append(pane)
    return panes


def _is_live(pane):
    return pane.get("pane_current_command") == "copilot" and pane.get("pane_dead") == "0"


def find_pane(environment, session_id=None):
    matches = [p for p in discover() if p.get("environment") == environment]
    live = [p for p in matches if _is_live(p)]
    if session_id is not None:
        selected = []
        for pane in live:
            try:
                identity = live_session(pane)
            except (Refused, OSError, ValueError):
                continue
            if identity["session_id"] == session_id:
                selected.append(pane)
        if len(selected) != 1:
            raise Refused(
                f"expected exactly one live Copilot pane in {environment} for session "
                f"{session_id}, found {len(selected)}"
            )
        return selected[0]
    if len(live) == 1:
        return live[0]
    if len(matches) != 1:
        raise Refused(
            f"ambiguous recipient: {len(matches)} panes in {environment}; "
            "pass --session-id for the reviewed session"
        )
    return matches[0]


def _process_table():
    table = {}
    for line in command(["ps", "-axo", "pid=,ppid=,comm="]).splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), parts[2].strip())
        except ValueError:
            continue
    return table


def live_session(pane):
    table = _process_table()
    root = int(pane["pane_pid"])
    children = {}
    for pid, (ppid, _comm) in table.items():
        children.setdefault(ppid, []).append(pid)
    family, pending = {root}, [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in family:
                family.add(child)
                pending.append(child)
    copilots = {
        pid for pid in family if pid in table and os.path.basename(table[pid][1]) == "copilot"
    }
    if not copilots:
        raise Refused(f"no live Copilot descendant of pane {pane.get('pane_id')}")
    pids = ",".join(str(pid) for pid in sorted(copilots))
    output = command(["lsof", "-a", "-p", pids, "-Fn"], allowed={0, 1})
    logs, locks = [], set()
    current = None
    for line in output.splitlines():
        if line.startswith("p"):
            try:
                current = int(line[1:])
            except ValueError:
                current = None
        elif line.startswith("n") and current in copilots:
            path = Path(line[1:])
            if _same_path(path.parent, logs_dir()):
                logs.append((path, current))
            elif (
                path.name == f"inuse.{current}.hold"
                and UUID_RE.match(path.parent.name)
                and _same_path(path.parent.parent, STATE_ROOT)
            ):
                locks.add((current, path.parent.name))
    resumed = set()
    for log, pid in logs:
        found = resumed_session(log, pid, pane)
        if found is not None:
            resumed.add(tuple(found))
    if resumed:
        if len(resumed) != 1:
            raise Refused("multiple runtime sessions found for one pane")
        pid, session_id = resumed.pop()
        return {"cli_pid": pid, "session_id": session_id}
    if len(locks) != 1:
        raise Refused("session lock missing or ambiguous; not guessing")
    pid, session_id = locks.pop()
    return {"cli_pid": pid, "session_id": session_id}


def resumed_session(log, pid, pane):
    log = Path(log)
    if not _same_path(log.parent, logs_dir()):
        return None
    if not re.fullmatch(rf"process-\d+-{int(pid)}\.log", log.name):
        return None
    session_id = None
    with open(log, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            changed = CHANGED_RE.search(line)
            resumed = RESUMED_RE.search(line)
            if changed and resumed:
                session_id = (
                    changed.group(2) if changed.start() > resumed.start() else resumed.group(1)
                )
            elif changed:
                session_id = changed.group(2)
            elif resumed:
                session_id = resumed.group(1)
    if session_id is None:
        return None
    events = STATE_ROOT / session_id / "events.jsonl"
    if not events.exists():
        return (int(pid), session_id)
    with open(events, encoding="utf-8") as handle:
        first = handle.readline()
    try:
        start = json.loads(first)
    except ValueError:
        start = None
    if (
        not isinstance(start, dict)
        or start.get("type") != "session.start"
        or not isinstance(start.get("data"), dict)
        or start["data"].get("sessionId") != session_id
    ):
        raise Refused(f"saved history does not match session {session_id}")
    expected = pane.get("environment")
    if expected:
        context = start["data"].get("context") or {}
        cwd = context.get("cwd") if isinstance(context, dict) else None
        if environment_for(cwd) != expected:
            raise Refused(f"session {session_id} belongs to a different environment")
    return (int(pid), session_id)


def turn_digest(user_event):
    if user_event is None:
        return H(json.dumps(None))
    data = user_event.get("data") or {}
    payload = [user_event.get("id"), user_event.get("timestamp"), str(data.get("content"))]
    return H(json.dumps(payload, ensure_ascii=False, separators=(", ", ": ")))


def _events_path(session_id):
    return STATE_ROOT / session_id / "events.jsonl"


def read_progress(session_id):
    path = _events_path(session_id)
    if not path.exists():
        return {
            "turn": turn_digest(None),
            "user": None,
            "assistant": None,
            "last_tool": None,
            "pending_forms": [],
            "history": "not_persisted",
        }
    user = assistant = last_tool = None
    forms = {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if kind == "user.message":
                user, assistant, last_tool = event, None, None
            elif kind == "assistant.message":
                if data.get("content") and data.get("channel") != "analysis":
                    assistant = event
            elif kind == "tool.execution_start":
                last_tool = {"timestamp": event.get("timestamp"), "name": data.get("toolName")}
                if data.get("toolName") == "ask_user":
                    forms[data.get("toolCallId")] = data.get("arguments", {})
            elif kind == "tool.execution_complete":
                forms.pop(data.get("toolCallId"), None)

    def summary(event, limit):
        if event is None:
            return None
        content = (event.get("data") or {}).get("content")
        return {"timestamp": event.get("timestamp"), "content": str(content)[:limit]}

    return {
        "turn": turn_digest(user),
        "user": summary(user, 2000),
        "assistant": summary(assistant, 8000),
        "last_tool": last_tool,
        "pending_forms": list(forms.values()),
    }


def _screen_lines(screen):
    lines = screen.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def input_state(pane, screen):
    if pane.get("pane_dead") != "0" or pane.get("pane_current_command") != "copilot":
        return "parked_or_not_copilot"
    if pane.get("pane_in_mode") != "0":
        return "copy_mode"
    if "Copilot needs information." in screen or "Asking user Waiting for response" in screen:
        return "approval_dialog"
    tail = _screen_lines(screen)[-24:]
    top = None
    for index, line in enumerate(tail):
        if line.lstrip().startswith("\u257b"):
            top = index
    if top is None:
        return "unknown_input"
    bottom = None
    for index in range(top + 1, len(tail)):
        if tail[index].lstrip().startswith("\u2579"):
            bottom = index
            break
    if bottom is None:
        return "unknown_input"
    composer = tail[top + 1:bottom]
    if not composer or any(line.strip() != "\u2503" for line in composer):
        return "nonempty_input"
    if any("esc esc interrupt" in line for line in tail[-4:]):
        return "busy"
    return "idle"


def _capture(pane_id):
    return command(["tmux", "capture-pane", "-p", "-t", pane_id])


def _input_context(screen):
    lines = screen.splitlines()
    top = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith("\u257b"):
            top = index
    if top is None:
        return NO_COMPOSER_NOTICE
    return "\n".join(lines[max(top - 1, 0):])


def inspect(environment, pane=None, session_id=None, screen_context=False):
    if pane is None:
        pane = find_pane(environment, session_id)
    screen = _capture(pane["pane_id"])
    result = {"pane": pane, "state": input_state(pane, screen)}
    if screen_context:
        result["input_context"] = _input_context(screen)
    if pane.get("pane_current_command") == "copilot":
        try:
            identity = live_session(pane)
            progress = read_progress(identity["session_id"])
        except (Refused, OSError, ValueError) as exc:
            result["identity_error"] = str(exc)
        else:
            result["identity"] = identity
            result["progress"] = progress
            if progress["pending_forms"]:
                result["state"] = "approval_dialog"
    return result


def recipient_snapshot(environment, allow_new=False, session_id=None, delivery="idle"):
    info = inspect(environment, session_id=session_id)
    pane = info["pane"]
    if TMUX_PANE and pane.get("pane_id") == TMUX_PANE:
        raise Refused("the recipient is the coordinator's own pane")
    state = info.get("state")
    if state not in DELIVERY_STATES.get(delivery, set()):
        raise Refused(
            f"{environment} is {state}, not eligible for {delivery} delivery; no input was sent"
        )
    identity = info.get("identity")
    if not identity:
        raise Refused(info.get("identity_error") or f"cannot pin down the session in {environment}")
    progress = info.get("progress") or {}
    unpersisted = progress.get("history") == "not_persisted"
    if unpersisted and not allow_new:
        raise Refused(
            f"{environment} has no saved history yet; use --allow-new-session only if "
            "that empty chat is the intended recipient"
        )
    snapshot = {
        "environment": environment,
        "pane_id": pane["pane_id"],
        "pane_pid": pane["pane_pid"],
        "cli_pid": identity["cli_pid"],
        "session_id": identity["session_id"],
        "turn": progress.get("turn"),
    }
    if delivery != "idle":
        snapshot["input_state"] = state
    if unpersisted:
        snapshot["new_session"] = True
    return snapshot


def prose(text):
    for char in text:
        if unicodedata.category(char) == "Cc" and char not in "\t\r\n":
            raise Refused(f"control character U+{ord(char):04X} is not allowed")
    message = " ".join(text.split())
    if not message:
        raise Refused("the message is empty")
    if message[0] in "/!":
        raise Refused("messages must not start with / or !")
    return message


def approval_digest(draft):
    bound = {key: draft[key] for key in DIGEST_KEYS if key in draft}
    return H(json.dumps(bound, sort_keys=True, ensure_ascii=False))


def _dump(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_private(path, data):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(_dump(data))
        handle.flush()
        os.fsync(handle.fileno())


def rewrite_private(path, data):
    fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC)
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(_dump(data))
        handle.flush()
        os.fsync(handle.fileno())


def _absolute(path, label):
    path = Path(path)
    if not path.is_absolute():
        raise Refused(f"{label} must be an absolute path")
    return path


def _check_delivery(delivery, reload_skills):
    if delivery not in DELIVERY_STATES or (reload_skills and delivery != "idle"):
        raise Refused(f"unsupported delivery mode: {delivery}")


def prepare(
    environment,
    message_file,
    output,
    allow_new=False,
    session_id=None,
    delivery="idle",
    reload_skills=False,
):
    _check_delivery(delivery, reload_skills)
    output = _absolute(output, "--output")
    if reload_skills:
        message = RELOAD_COMMAND
    else:
        source = _absolute(message_file, "--message-file")
        message = prose(source.read_text(encoding="utf-8"))
    recipient = recipient_snapshot(
        environment, allow_new=allow_new, session_id=session_id, delivery=delivery
    )
    draft = {
        "version": 1,
        "recipient": recipient,
        "message": message,
        "message_sha256": H(message),
    }
    if reload_skills:
        draft["operation"] = RELOAD_OPERATION
    if delivery != "idle":
        draft["delivery"] = delivery
    draft["approval_sha256"] = approval_digest(draft)
    write_private(output, draft)
    return draft


def _load_draft(draft_file):
    path = _absolute(draft_file, "draft file")
    draft = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(draft, dict) or draft.get("version") != 1:
        raise Refused("unsupported draft version")
    if H(draft["message"]) != draft.get("message_sha256"):
        raise Refused("draft message differs from approval")
    if approval_digest(draft) != draft.get("approval_sha256"):
        raise Refused("draft differs from approval")
    return path, draft


def _receipt_path(draft_path):
    return Path(str(draft_path) + ".receipt.json")


def send(draft_file, approved_sha256):
    path, draft = _load_draft(draft_file)
    if draft["approval_sha256"] != approved_sha256:
        raise Refused("draft differs from approval")
    delivery = draft.get("delivery", "idle")
    reload_skills = "operation" in draft
    _check_delivery(delivery, reload_skills)
    message = draft["message"]
    if reload_skills:
        if draft["operation"] != RELOAD_OPERATION or message != RELOAD_COMMAND:
            raise Refused("reload drafts may only carry /skills reload")
    elif message != prose(message):
        raise Refused("draft message is not canonical prose")
    stored = draft["recipient"]

    def snapshot():
        return recipient_snapshot(
            stored["environment"],
            delivery=delivery,
            session_id=stored["session_id"],
            allow_new=bool(stored.get("new_session")),
        )

    if snapshot() != stored:
        raise Refused("recipient changed since review; prepare and approve a new draft")
    receipt_path = _receipt_path(path)
    receipt = {
        "status": "attempting",
        "recipient": stored,
        "message_sha256": draft["message_sha256"],
        "approval_sha256": draft["approval_sha256"],
        "delivery_mode": delivery,
    }
    if reload_skills:
        receipt["operation"] = RELOAD_OPERATION
    write_private(receipt_path, receipt)
    pane_id = stored["pane_id"]
    try:
        events = _events_path(stored["session_id"])
        receipt["event_offset"] = events.stat().st_size if events.exists() else 0
        rewrite_private(receipt_path, receipt)
        before = _capture(pane_id) if reload_skills else None
        if snapshot() != stored:
            raise Refused("recipient changed during preflight; nothing was typed")
        command(["tmux", "send-keys", "-t", pane_id, "-l", message])
        command(["tmux", "send-keys", "-t", pane_id, "C-q" if delivery == "queue" else "Enter"])
        if reload_skills:
            evidence = await_reload(stored, before)
            receipt["status"] = "reloaded" if evidence else "unconfirmed"
        else:
            evidence = await_receipt(stored["session_id"], message, receipt["event_offset"])
            receipt["status"] = delivery_status(evidence)
        receipt["evidence"] = evidence
    except Exception as exc:
        receipt["status"] = "uncertain_do_not_retry"
        receipt["error"] = str(exc)
        raise
    finally:
        rewrite_private(receipt_path, receipt)
    return receipt


def await_receipt(session_id, message, offset, timeout=5):
    deadline = time.monotonic() + timeout
    path = _events_path(session_id)
    while True:
        if path.exists():
            with open(path, "rb") as handle:
                handle.seek(offset)
                for raw in handle:
                    try:
                        event = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                    if not isinstance(event, dict) or event.get("type") != "user.message":
                        continue
                    data = event.get("data") or {}
                    if data.get("content") == message:
                        return {
                            "event_id": event.get("id"),
                            "timestamp": event.get("timestamp"),
                            "delivery": data.get("delivery"),
                        }
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL_INTERVAL)


def delivery_status(evidence):
    if not evidence:
        return "unconfirmed"
    if evidence.get("delivery") in ("queued", "steering"):
        return evidence["delivery"]
    return "received"


def receipt_offset(recipient):
    turn = recipient["turn"]
    if turn == turn_digest(None):
        return 0
    path = _events_path(recipient["session_id"])
    if path.exists():
        position = 0
        with open(path, "rb") as handle:
            for raw in handle:
                position += len(raw)
                try:
                    event = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
                if (
                    isinstance(event, dict)
                    and event.get("type") == "user.message"
                    and turn_digest(event) == turn
                ):
                    return position
    raise Refused("cannot reconcile: the bound turn is not in the saved history")


def confirm(draft_file):
    path, draft = _load_draft(draft_file)
    receipt_path = _receipt_path(path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for key in ("approval_sha256", "message_sha256", "recipient"):
        if receipt.get(key) != draft[key]:
            raise Refused(f"receipt {key} does not match the draft")
    if receipt.get("status") in CONFIRMED_STATUSES:
        return receipt
    if "operation" in draft:
        raise Refused("reloads need native UI confirmation and cannot be reconciled")
    recipient = draft["recipient"]
    offset = receipt.get("event_offset")
    if offset is None:
        offset = receipt_offset(recipient)
    evidence = await_receipt(recipient["session_id"], draft["message"], offset, timeout=0)
    if evidence:
        receipt["status"] = delivery_status(evidence)
        receipt["evidence"] = evidence
        rewrite_private(receipt_path, receipt)
    return receipt


def _confirming_line(line):
    return bool(RELOAD_SUCCESS_RE.search(line)) and not RELOAD_FAILURE_RE.search(line)


def await_reload(recipient, before, timeout=5):
    deadline = time.monotonic() + timeout
    seen = {line.strip() for line in (before or "").splitlines()}
    while True:
        screen = _capture(recipient["pane_id"])
        for line in screen.splitlines():
            text = line.strip()
            if not text or text in seen or not _confirming_line(text):
                continue
            current = recipient_snapshot(
                recipient["environment"],
                session_id=recipient["session_id"],
                allow_new=bool(recipient.get("new_session")),
            )
            for key in set(current) | set(recipient):
                if key != "turn" and current.get(key) != recipient.get(key):
                    raise Refused("recipient identity changed after the reload")
            return {"confirmation": text[:500]}
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL_INTERVAL)


def _status(environment, progress, screen_context):
    def trim(result):
        if not progress:
            result.pop("progress", None)
        return result

    try:
        result = trim(inspect(environment, screen_context=screen_context))
        return dict({"environment": environment}, **result)
    except Refused as exc:
        candidates = []
        for pane in discover():
            if pane.get("environment") != environment:
                continue
            try:
                candidates.append(
                    trim(inspect(environment, pane=pane, screen_context=screen_context))
                )
            except (Refused, OSError, ValueError) as inner:
                candidates.append({"pane": pane, "error": str(inner)})
        return {"environment": environment, "error": str(exc), "candidates": candidates}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="inter_env.py",
        description="Inspect Copilot chats in the ai-agents tmux session and deliver approved prompts.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    status = sub.add_parser("status", help="read-only inspection of one or all environments")
    status.add_argument("environment", nargs="?", choices=ENVIRONMENTS)
    status.add_argument("--progress", action="store_true", help="include recipient progress")
    status.add_argument(
        "--screen-context", action="store_true", help="include the composer area of the screen"
    )

    prep = sub.add_parser("prepare", help="write a draft bound to one recipient; types nothing")
    prep.add_argument("environment", choices=ENVIRONMENTS)
    prep.add_argument("--message-file", required=True, help="absolute path of the prose message")
    prep.add_argument("--output", required=True, help="new absolute JSON path for the draft")
    prep.add_argument("--delivery", choices=sorted(DELIVERY_STATES), default="idle")
    prep.add_argument("--session-id", help="exact session that was reviewed")
    prep.add_argument("--allow-new-session", action="store_true")

    reload_parser = sub.add_parser("prepare-reload", help="draft a /skills reload (idle only)")
    reload_parser.add_argument("environment", choices=ENVIRONMENTS)
    reload_parser.add_argument("--output", required=True, help="new absolute JSON path for the draft")

    send_parser = sub.add_parser("send", help="deliver an approved draft exactly once")
    send_parser.add_argument("draft_file")
    send_parser.add_argument("--approved-sha256", required=True)

    confirm_parser = sub.add_parser("confirm", help="reconcile a sent draft; sends nothing")
    confirm_parser.add_argument("draft_file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.subcommand == "status":
            names = [args.environment] if args.environment else list(ENVIRONMENTS)
            result = [_status(name, args.progress, args.screen_context) for name in names]
        elif args.subcommand == "prepare":
            result = prepare(
                args.environment,
                args.message_file,
                args.output,
                allow_new=args.allow_new_session,
                session_id=args.session_id,
                delivery=args.delivery,
            )
        elif args.subcommand == "prepare-reload":
            result = prepare(args.environment, None, args.output, reload_skills=True)
        elif args.subcommand == "send":
            result = send(args.draft_file, args.approved_sha256)
        else:
            result = confirm(args.draft_file)
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if isinstance(result, dict) and result.get("status") == "unconfirmed":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

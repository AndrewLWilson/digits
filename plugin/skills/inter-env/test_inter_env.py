"""Mocked acceptance tests for inter_env.py (no tmux, no real home, no network)."""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inter_env  # noqa: E402

SID = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
H = inter_env.H
ORIGINAL_AWAIT_RECEIPT = inter_env.await_receipt


def pane(pane_id="%31", path=None, command="copilot", in_mode="0", dead="0", pid="100"):
    return {
        "session_name": "ai-agents",
        "pane_id": pane_id,
        "pane_pid": pid,
        "pane_current_path": path or "",
        "pane_current_command": command,
        "pane_title": "title",
        "pane_in_mode": in_mode,
        "pane_dead": dead,
        "environment": inter_env.environment_for(path) if path else "left_thumb",
    }


def composer(body="\u2503", footer="ctrl+c Exit", above=("timeline",)):
    return "\n".join(list(above) + ["\u257b", body, "\u2579", footer]) + "\n"


class Recorder:
    """Stands in for inter_env.command and records every call."""

    def __init__(self, responses=None, fail_on=None):
        self.calls = []
        self.responses = responses or {}
        self.fail_on = fail_on

    def __call__(self, args, allowed=frozenset({0})):
        self.calls.append(list(args))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise inter_env.Refused("simulated tmux failure")
        key = args[0] if args[0] != "tmux" else "tmux " + args[1]
        response = self.responses.get(key, "")
        return response(args) if callable(response) else response


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.state = self.tmp / "copilot" / "session-state"
        (self.state / SID).mkdir(parents=True)
        self.logs = self.tmp / "copilot" / "logs"
        self.logs.mkdir()
        self.events = self.state / SID / "events.jsonl"
        self.events.write_text("")
        self.work = self.tmp / "session-folder"
        self.work.mkdir()
        self.message_file = self.work / "message.txt"
        self.message_file.write_text("Read the handoff.\nThen wait.\n")
        self.snapshot = {
            "environment": "left_thumb",
            "pane_id": "%31",
            "pane_pid": "100",
            "cli_pid": 200,
            "session_id": SID,
            "turn": "original-turn",
        }
        self.recorder = Recorder()
        for name, value in (
            ("HOME", self.home),
            ("STATE_ROOT", self.state),
            ("TMUX_PANE", "%1"),
            ("command", self.recorder),
        ):
            patcher = mock.patch.object(inter_env, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _cleanup(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def patch(self, name, value):
        patcher = mock.patch.object(inter_env, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mock_snapshot(self, snapshot=None):
        snap = dict(snapshot or self.snapshot)

        def fake(environment, allow_new=False, session_id=None, delivery="idle"):
            result = dict(snap, environment=environment)
            if delivery != "idle":
                result["input_state"] = "busy"
            return result

        self.patch("recipient_snapshot", fake)
        return fake

    def prepare(self, name="draft.json", **kwargs):
        return inter_env.prepare(
            "left_thumb", str(self.message_file), str(self.work / name), **kwargs
        )

    def rewrite(self, path, draft):
        Path(path).write_text(json.dumps(draft))

    def append_event(self, event):
        with open(self.events, "a") as handle:
            handle.write(json.dumps(event) + "\n")


class ProseAndDraftTests(Base):
    def test_35_prose_normalization(self):
        self.assertEqual(
            inter_env.prose("Read '$HOME'; $(echo literal)\nthen wait."),
            "Read '$HOME'; $(echo literal) then wait.",
        )
        for bad in ("Read\x9b", "Read\x00", "", "Read\x7f", "/exit", "Read\x1b[2J", " ! echo no"):
            with self.subTest(bad=bad), self.assertRaises(inter_env.Refused):
                inter_env.prose(bad)

    def test_36_prepare_private_inert_exclusive(self):
        self.mock_snapshot()
        draft = self.prepare()
        self.assertEqual(self.recorder.calls, [])
        self.assertEqual(draft["message"], "Read the handoff. Then wait.")
        mode = stat.S_IMODE((self.work / "draft.json").stat().st_mode)
        self.assertEqual(mode, 0o600)
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_37_environment_roots(self):
        self.assertEqual(inter_env.environment_for(self.home / "left_thumb" / "repo"), "left_thumb")
        self.assertIsNone(inter_env.environment_for(self.home / "thumb"))
        self.assertIsNone(inter_env.environment_for(self.home / "left_thumb_old"))
        self.assertIsNone(inter_env.environment_for(self.tmp / "elsewhere" / "left_thumb"))


class DiscoveryTests(Base):
    def test_38_duplicate_parked_panes_refused(self):
        lt = str(self.home / "left_thumb")
        panes = [pane("%1", lt, command="fish"), pane("%2", lt, command="zsh")]
        self.patch("discover", lambda: panes)
        with self.assertRaises(inter_env.Refused):
            inter_env.find_pane("left_thumb")

    def test_39_input_states(self):
        live = pane()
        cases = [
            (live, composer(), "idle"),
            (live, composer(footer="ctrl+c Exit esc esc interrupt"), "busy"),
            (live, composer(body="\u2503 typed", footer="ctrl+c esc esc interrupt"), "nonempty_input"),
            (live, "Copilot needs information.\n" + composer(), "approval_dialog"),
            (live, composer(body="\u2503 typed"), "nonempty_input"),
            (pane(in_mode="1"), composer(), "copy_mode"),
            (pane(command="fish"), composer(), "parked_or_not_copilot"),
            (live, "just some arbitrary text\n", "unknown_input"),
        ]
        for p, screen, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(inter_env.input_state(p, screen), expected)

    def lsof_responses(self, paths_by_pid):
        ps = "  100     1 -zsh\n  200   100 copilot\n  201   200 /usr/local/bin/copilot\n  300     1 copilot\n"

        def lsof(args):
            self.assertEqual(args[:4], ["lsof", "-a", "-p", "200,201"])
            lines = []
            for pid, paths in paths_by_pid.items():
                lines.append(f"p{pid}")
                for path in paths:
                    lines += ["f3", f"n{path}"]
            return "\n".join(lines) + "\n"

        self.recorder.responses = {"ps": ps, "lsof": lsof}

    def test_40_session_from_lock(self):
        self.lsof_responses({200: [self.state / SID / "inuse.200.hold"]})
        self.assertEqual(
            inter_env.live_session(pane()), {"cli_pid": 200, "session_id": SID}
        )

    def test_41_ambiguous_locks(self):
        self.lsof_responses(
            {200: [self.state / SID / "inuse.200.hold", self.state / OTHER / "inuse.200.hold"]}
        )
        with self.assertRaises(inter_env.Refused):
            inter_env.live_session(pane())

    def test_42_runtime_log_wins(self):
        log = self.logs / "process-123-200.log"
        log.write_text(
            f"2026 [INFO] Resumed session: {OTHER}\n"
            "noise\n"
            f"2026 [INFO] Resumed session: {SID}  \n"
        )
        self.events.write_text(
            json.dumps(
                {
                    "type": "session.start",
                    "data": {"sessionId": SID, "context": {"cwd": str(self.home / "left_thumb" / "repo")}},
                }
            )
            + "\n"
        )
        self.lsof_responses(
            {200: [log, self.state / OTHER / "inuse.200.hold", self.state / SID / "inuse.200.hold"]}
        )
        p = pane(path=str(self.home / "left_thumb"))
        self.assertEqual(inter_env.live_session(p), {"cli_pid": 200, "session_id": SID})
        with self.assertRaises(inter_env.Refused):
            inter_env.resumed_session(log, 200, pane(path=str(self.home / "right_thumb")))
        self.assertIsNone(inter_env.resumed_session(log, 201, p))

    def test_42b_session_changed_arrow_takes_second_uuid(self):
        log = self.logs / "process-9-200.log"
        log.write_text(f"[INFO] Session changed ({OTHER} \u2192 {SID})\n")
        self.events.unlink()
        self.assertEqual(inter_env.resumed_session(log, 200, pane()), (200, SID))

    def test_43_exact_session_selection(self):
        lt = str(self.home / "left_thumb")
        first, second = pane("%1", lt, pid="10"), pane("%2", lt, pid="20")
        panes = [first, second]
        self.patch("discover", lambda: panes)
        sessions = {"10": OTHER, "20": SID}
        self.patch(
            "live_session",
            lambda p: {"cli_pid": int(p["pane_pid"]) + 1, "session_id": sessions[p["pane_pid"]]},
        )
        self.assertIs(inter_env.find_pane("left_thumb", SID), second)
        first["pane_current_command"] = "fish"
        self.assertIs(inter_env.find_pane("left_thumb"), second)


class ProgressTests(Base):
    def test_44_missing_history(self):
        self.events.unlink()
        self.assertEqual(inter_env.read_progress(SID)["history"], "not_persisted")
        self.assertIsNone(inter_env.await_receipt(SID, "hello", 0, timeout=0))
        self.assertFalse(self.events.exists())

    def test_52_pending_form_and_new_turn(self):
        for event in (
            {"type": "user.message", "id": "u1", "data": {"content": "old"}},
            {"type": "assistant.message", "data": {"content": "old result"}},
            {"type": "user.message", "id": "u2", "data": {"content": "new"}},
            {
                "type": "tool.execution_start",
                "data": {
                    "toolName": "ask_user",
                    "toolCallId": "c1",
                    "arguments": {"message": "Approve investigation?"},
                },
            },
        ):
            self.append_event(event)
        progress = inter_env.read_progress(SID)
        self.assertIsNone(progress["assistant"])
        self.assertEqual(progress["user"]["content"], "new")
        self.assertEqual(progress["pending_forms"], [{"message": "Approve investigation?"}])
        self.assertNotIn("history", progress)
        self.append_event({"type": "tool.execution_complete", "data": {"toolCallId": "c1"}})
        self.assertEqual(inter_env.read_progress(SID)["pending_forms"], [])

    def test_50_legacy_offset(self):
        event = {"type": "user.message", "id": "u1", "timestamp": "t", "data": {"content": "go"}}
        self.append_event(event)
        turn = inter_env.read_progress(SID)["turn"]
        recipient = dict(self.snapshot, turn=turn)
        self.assertEqual(inter_env.receipt_offset(recipient), self.events.stat().st_size)
        self.assertEqual(inter_env.receipt_offset(dict(self.snapshot, turn=H("null"))), 0)
        with self.assertRaises(inter_env.Refused):
            inter_env.receipt_offset(dict(self.snapshot, turn="unknown"))

    def test_51_input_context(self):
        screen = "\n".join(
            [
                "Thinking about the plan",
                "\u25cf timeline entry",
                "",
                "\u257b",
                "\u2503",
                "\u2579",
                "footer hints",
            ]
        )
        self.recorder.responses = {"tmux capture-pane": screen}
        parked = pane(command="fish")
        result = inter_env.inspect("left_thumb", pane=parked, screen_context=True)
        self.assertEqual(result["state"], "parked_or_not_copilot")
        self.assertNotIn("Thinking", result["input_context"])
        self.assertNotIn("timeline", result["input_context"])
        self.assertIn("footer hints", result["input_context"])
        self.assertNotIn("identity", result)

    def test_59_only_new_matching_events(self):
        message = "Read the handoff. Then wait."
        self.append_event({"type": "user.message", "id": "old", "data": {"content": message}})
        offset = self.events.stat().st_size
        self.assertIsNone(inter_env.await_receipt(SID, message, offset, timeout=0))
        self.append_event({"type": "user.message", "id": "new", "data": {"content": message}})
        evidence = inter_env.await_receipt(SID, message, offset, timeout=0)
        self.assertEqual(evidence["event_id"], "new")


class SnapshotTests(Base):
    def fake_inspect(self, state="idle", identity=True, history=None, pane_id="%31"):
        progress = {"turn": "original-turn", "pending_forms": []}
        if history:
            progress["history"] = history
        result = {"pane": pane(pane_id), "state": state, "progress": progress}
        if identity:
            result["identity"] = {"cli_pid": 200, "session_id": SID}
        else:
            result["identity_error"] = "no live Copilot descendant"
        self.patch("inspect", lambda environment, **kw: result)

    def test_45_busy_needs_explicit_mode_forms_block(self):
        self.fake_inspect(state="busy")
        with self.assertRaises(inter_env.Refused):
            inter_env.recipient_snapshot("left_thumb")
        for mode in ("submit", "queue"):
            snap = inter_env.recipient_snapshot("left_thumb", delivery=mode)
            self.assertEqual(snap["input_state"], "busy")
        self.fake_inspect(state="approval_dialog")
        for mode in ("idle", "submit", "queue"):
            with self.subTest(mode=mode), self.assertRaises(inter_env.Refused):
                inter_env.recipient_snapshot("left_thumb", delivery=mode)

    def test_45b_pending_form_marks_approval_dialog(self):
        self.recorder.responses = {"tmux capture-pane": composer()}
        self.patch("live_session", lambda p: {"cli_pid": 200, "session_id": SID})
        self.append_event(
            {"type": "tool.execution_start", "data": {"toolName": "ask_user", "toolCallId": "c"}}
        )
        result = inter_env.inspect("left_thumb", pane=pane())
        self.assertEqual(result["state"], "approval_dialog")
        self.assertEqual(result["progress"]["pending_forms"], [{}])

    def test_46_new_chat_opt_in(self):
        self.fake_inspect(history="not_persisted")
        with self.assertRaises(inter_env.Refused):
            inter_env.recipient_snapshot("left_thumb")
        snap = inter_env.recipient_snapshot("left_thumb", allow_new=True)
        self.assertTrue(snap["new_session"])
        self.assertNotIn("input_state", snap)

    def test_53_own_pane_and_missing_identity(self):
        self.fake_inspect(pane_id="%1")
        with self.assertRaises(inter_env.Refused):
            inter_env.recipient_snapshot("left_thumb")
        self.fake_inspect(identity=False)
        with self.assertRaisesRegex(inter_env.Refused, "no live Copilot"):
            inter_env.recipient_snapshot("left_thumb")

    def test_snapshot_shape(self):
        self.fake_inspect()
        self.assertEqual(inter_env.recipient_snapshot("left_thumb"), self.snapshot)


class SendTests(Base):
    def setUp(self):
        super().setUp()
        self.mock_snapshot()
        self.receipts = []

        def fake_receipt(session_id, message, offset, timeout=5):
            self.receipts.append((session_id, message, offset))
            return self.evidence

        self.evidence = {"event_id": "e1", "timestamp": "t", "delivery": None}
        self.patch("await_receipt", fake_receipt)

    def test_47_submit_vs_queue(self):
        for mode, key, observed in (("submit", "Enter", "steering"), ("queue", "C-q", "queued")):
            with self.subTest(mode=mode):
                draft = self.prepare(f"{mode}.json", delivery=mode)
                self.assertEqual(draft["delivery"], mode)
                self.assertEqual(draft["recipient"]["input_state"], "busy")
                altered = dict(draft, delivery="idle")
                self.assertNotEqual(inter_env.approval_digest(altered), draft["approval_sha256"])
                self.evidence = {"event_id": "e", "timestamp": "t", "delivery": observed}
                receipt = inter_env.send(str(self.work / f"{mode}.json"), draft["approval_sha256"])
                self.assertEqual(receipt["status"], observed)
                self.assertEqual(receipt["delivery_mode"], mode)
                self.assertEqual(self.recorder.calls[-1], ["tmux", "send-keys", "-t", "%31", key])

    def test_48_reload_is_idle_only(self):
        with self.assertRaises(inter_env.Refused):
            inter_env.prepare(
                "left_thumb", None, str(self.work / "r.json"), delivery="submit", reload_skills=True
            )
        self.assertFalse((self.work / "r.json").exists())

    def test_49_delayed_confirmation_without_resend(self):
        self.evidence = None
        draft = self.prepare()
        path = str(self.work / "draft.json")
        receipt = inter_env.send(path, draft["approval_sha256"])
        self.assertEqual(receipt["status"], "unconfirmed")
        self.patch("await_receipt", ORIGINAL_AWAIT_RECEIPT)
        self.append_event(
            {"type": "user.message", "id": "late", "data": {"content": draft["message"], "delivery": "steering"}}
        )
        calls_before = len(self.recorder.calls)
        confirmed = inter_env.confirm(path)
        self.assertEqual(confirmed["status"], "steering")
        self.assertEqual(confirmed["evidence"]["event_id"], "late")
        self.assertEqual(len(self.recorder.calls), calls_before)
        stored = json.loads(Path(path + ".receipt.json").read_text())
        self.assertEqual(stored["status"], "steering")
        with self.assertRaises(FileExistsError):
            inter_env.send(path, draft["approval_sha256"])

    def test_54_tampered_payload_or_hash(self):
        draft = self.prepare()
        path = self.work / "draft.json"
        with self.assertRaises(inter_env.Refused):
            inter_env.send(str(path), "0" * 64)
        tampered = dict(draft, message="Delete everything.")
        self.rewrite(path, tampered)
        with self.assertRaises(inter_env.Refused):
            inter_env.send(str(path), draft["approval_sha256"])
        self.assertEqual(self.recorder.calls, [])

    def test_55_modified_destination(self):
        draft = self.prepare()
        path = self.work / "draft.json"
        moved = json.loads(json.dumps(draft))
        moved["recipient"]["environment"] = "right_thumb"
        moved["approval_sha256"] = inter_env.approval_digest(moved)
        self.rewrite(path, moved)
        with self.assertRaises(inter_env.Refused):
            inter_env.send(str(path), draft["approval_sha256"])
        self.assertEqual(self.recorder.calls, [])

    def test_56_changed_identity(self):
        changes = {"session_id": OTHER, "cli_pid": 999, "pane_pid": "555", "turn": "newer-turn"}
        for index, (key, value) in enumerate(changes.items()):
            with self.subTest(key=key):
                self.mock_snapshot()
                draft = self.prepare(f"d{index}.json")
                self.mock_snapshot(dict(self.snapshot, **{key: value}))
                with self.assertRaises(inter_env.Refused):
                    inter_env.send(str(self.work / f"d{index}.json"), draft["approval_sha256"])
                self.assertEqual(self.recorder.calls, [])
                self.assertFalse((self.work / f"d{index}.json.receipt.json").exists())

    def test_57_literal_one_shot_send(self):
        draft = self.prepare()
        path = str(self.work / "draft.json")
        receipt = inter_env.send(path, draft["approval_sha256"])
        self.assertEqual(receipt["status"], "received")
        self.assertEqual(receipt["event_offset"], 0)
        self.assertEqual(
            self.recorder.calls[0],
            ["tmux", "send-keys", "-t", "%31", "-l", "Read the handoff. Then wait."],
        )
        mode = stat.S_IMODE(Path(path + ".receipt.json").stat().st_mode)
        self.assertEqual(mode, 0o600)
        with self.assertRaises(FileExistsError):
            inter_env.send(path, draft["approval_sha256"])
        self.assertEqual(len(self.recorder.calls), 2)

    def test_58_partial_failure(self):
        draft = self.prepare()
        path = str(self.work / "draft.json")
        self.recorder.fail_on = 2
        with self.assertRaises(inter_env.Refused):
            inter_env.send(path, draft["approval_sha256"])
        stored = json.loads(Path(path + ".receipt.json").read_text())
        self.assertEqual(stored["status"], "uncertain_do_not_retry")
        self.assertIn("simulated", stored["error"])
        with self.assertRaises(FileExistsError):
            inter_env.send(path, draft["approval_sha256"])
        self.assertEqual(len(self.recorder.calls), 2)


class ReloadTests(Base):
    def setUp(self):
        super().setUp()
        self.mock_snapshot()

    def prepare_reload(self, name="reload.json"):
        return inter_env.prepare("left_thumb", None, str(self.work / name), reload_skills=True)

    def test_60_reload_draft_binding(self):
        draft = self.prepare_reload()
        self.assertEqual(self.recorder.calls, [])
        self.assertEqual(draft["message"], "/skills reload")
        self.assertEqual(draft["operation"], "reload-skills")
        stripped = {k: v for k, v in draft.items() if k != "operation"}
        self.assertNotEqual(inter_env.approval_digest(stripped), draft["approval_sha256"])

    def test_61_reload_cannot_become_another_command(self):
        draft = self.prepare_reload()
        forged = dict(draft, message="/exit", message_sha256=H("/exit"))
        forged["approval_sha256"] = inter_env.approval_digest(forged)
        path = self.work / "reload.json"
        self.rewrite(path, forged)
        with self.assertRaises(inter_env.Refused):
            inter_env.send(str(path), forged["approval_sha256"])
        self.assertEqual(self.recorder.calls, [])

    def test_62_reload_shares_guards(self):
        def busy(environment, **kwargs):
            raise inter_env.Refused("left_thumb is busy; no input was sent")

        self.patch("recipient_snapshot", busy)
        with self.assertRaises(inter_env.Refused):
            self.prepare_reload()
        self.assertEqual(self.recorder.calls, [])
        self.assertFalse((self.work / "reload.json").exists())

    def test_63_reload_one_shot_with_native_confirmation(self):
        self.patch("await_reload", lambda recipient, before, timeout=5: {"confirmation": "Reloaded 9 skills"})

        def never(*args, **kwargs):
            raise AssertionError("user-event receipt must not be consulted for reloads")

        self.patch("await_receipt", never)
        self.recorder.responses = {"tmux capture-pane": "before screen\n"}
        draft = self.prepare_reload()
        path = str(self.work / "reload.json")
        receipt = inter_env.send(path, draft["approval_sha256"])
        self.assertEqual(receipt["status"], "reloaded")
        self.assertEqual(receipt["operation"], "reload-skills")
        self.assertEqual(
            self.recorder.calls,
            [
                ["tmux", "capture-pane", "-p", "-t", "%31"],
                ["tmux", "send-keys", "-t", "%31", "-l", "/skills reload"],
                ["tmux", "send-keys", "-t", "%31", "Enter"],
            ],
        )
        with self.assertRaises(FileExistsError):
            inter_env.send(path, draft["approval_sha256"])
        self.assertEqual(len(self.recorder.calls), 3)

    def test_63b_unconfirmed_reload_cannot_be_reconciled(self):
        self.patch("await_reload", lambda recipient, before, timeout=5: None)
        draft = self.prepare_reload()
        path = str(self.work / "reload.json")
        self.assertEqual(inter_env.send(path, draft["approval_sha256"])["status"], "unconfirmed")
        with self.assertRaises(inter_env.Refused):
            inter_env.confirm(path)

    def test_64_fresh_success_required(self):
        recipient = dict(self.snapshot)
        before = "older output\n  Reloaded 9 skills\n"
        for screen in (
            before,
            before + "Skills were not loaded\n",
            before + "Failed: reloaded 0 skills\n",
        ):
            with self.subTest(screen=screen):
                self.recorder.responses = {"tmux capture-pane": screen}
                self.assertIsNone(inter_env.await_reload(recipient, before, timeout=0))
        self.recorder.responses = {"tmux capture-pane": "older output\nReloaded 9 skills\n"}
        self.mock_snapshot(dict(self.snapshot, turn="later-turn"))
        self.assertEqual(
            inter_env.await_reload(recipient, "older output\n", timeout=0),
            {"confirmation": "Reloaded 9 skills"},
        )
        self.mock_snapshot(dict(self.snapshot, cli_pid=999))
        with self.assertRaises(inter_env.Refused):
            inter_env.await_reload(recipient, "older output\n", timeout=0)


class CliTests(Base):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = inter_env.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_65_exit_codes(self):
        self.mock_snapshot()
        self.patch("await_receipt", lambda *a, **k: None)
        draft_path = str(self.work / "draft.json")
        code, out, err = self.run_cli(
            ["prepare", "left_thumb", "--message-file", str(self.message_file), "--output", draft_path]
        )
        self.assertEqual(code, 0, err)
        digest = json.loads(out)["approval_sha256"]
        code, out, _ = self.run_cli(["send", draft_path, "--approved-sha256", digest])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["status"], "unconfirmed")
        code, out, err = self.run_cli(["send", draft_path, "--approved-sha256", digest])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("Refused:"))
        code, out, err = self.run_cli(["send", draft_path, "--approved-sha256", "bad"])
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("Refused:"))
        code, _, err = self.run_cli(
            ["prepare", "left_thumb", "--message-file", "relative.txt", "--output", str(self.work / "x.json")]
        )
        self.assertEqual(code, 2)
        self.assertIn("Refused:", err)

    def test_status_lists_candidates_on_refusal(self):
        lt = str(self.home / "left_thumb")
        panes = [pane("%1", lt), pane("%2", lt)]
        self.patch("discover", lambda: panes)
        self.patch("live_session", lambda p: {"cli_pid": 1, "session_id": SID})
        self.recorder.responses = {"tmux capture-pane": composer()}
        code, out, _ = self.run_cli(["status", "left_thumb"])
        self.assertEqual(code, 0)
        (entry,) = json.loads(out)
        self.assertIn("error", entry)
        self.assertEqual([c["pane"]["pane_id"] for c in entry["candidates"]], ["%1", "%2"])
        self.assertNotIn("progress", entry["candidates"][0])


if __name__ == "__main__":
    unittest.main()

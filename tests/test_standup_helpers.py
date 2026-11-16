"""Tests for the standup-update shell helpers, run against stub executables."""

import datetime
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugin" / "skills" / "standup-update"
GITHUB = SKILL / "fetch-github-activity.sh"
JIRA = SKILL / "fetch-jira-activity.sh"
RUNNER = SKILL / "run-scheduled.sh"

FAKE_EMAIL = "someone@example.com"
FAKE_TOKEN = "fake-token-value-0123456789"

STUB_PREAMBLE = """\
import json, os, sys
args = sys.argv[1:]
name = os.path.basename(sys.argv[0])
stdin_data = sys.stdin.read() if name == "curl" else ""
with open(os.path.join(os.environ["HOME"], "calls.jsonl"), "a") as log:
    log.write(json.dumps({"name": name, "args": args, "stdin": stdin_data}) + "\\n")
"""


@unittest.skipUnless(shutil.which("jq"), "jq is required for the standup helpers")
class StandupHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.bin = self.home / ".local" / "bin"
        self.bin.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, name, body=""):
        path = self.bin / name
        path.write_text(
            "#!" + sys.executable + "\n" + STUB_PREAMBLE + textwrap.dedent(body)
        )
        path.chmod(0o755)

    def run_script(self, script, *args, env=None):
        environment = {
            "HOME": str(self.home),
            "TZ": "UTC",
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
        }
        environment.update(env or {})
        return subprocess.run(
            ["bash", str(script), *args],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self, name=None):
        log = self.home / "calls.jsonl"
        if not log.exists():
            return []
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        return [row for row in rows if name is None or row["name"] == name]

    # GitHub helper -----------------------------------------------------

    def gh_stub(self, auth_ok=True, detail_ok=True):
        self.stub(
            "gh",
            f"""
            if args[0] == "auth":
                sys.exit(0 if {auth_ok!r} else 1)
            if args[0] == "search":
                print(json.dumps([{{
                    "number": 7, "repository": {{"name": "project", "nameWithOwner": "example/project"}},
                    "state": "open", "title": "Search title", "updatedAt": "2026-11-05T10:00:00Z",
                    "url": "https://github.com/example/project/pull/7"}}]))
                sys.exit(0)
            if args[0] == "pr":
                if not {detail_ok!r}:
                    print("not found", file=sys.stderr)
                    sys.exit(1)
                print(json.dumps({{"number": 7, "title": "Search title", "state": "MERGED",
                    "reviewDecision": "APPROVED", "isDraft": False,
                    "url": "https://github.com/example/project/pull/7", "body": "Overview: why it matters"}}))
                sys.exit(0)
            sys.exit(2)
            """,
        )

    def test_github_rows_are_enriched_with_live_details(self):
        self.gh_stub()
        result = self.run_script(GITHUB, "2026-11-05")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body"], "Overview: why it matters")
        self.assertEqual(rows[0]["state"], "MERGED")
        self.assertEqual(rows[0]["reviewDecision"], "APPROVED")
        self.assertEqual(rows[0]["repository"]["nameWithOwner"], "example/project")
        calls = self.calls("gh")
        self.assertEqual([c["args"][0] for c in calls], ["auth", "search", "pr"])
        self.assertIn("example/project", calls[-1]["args"])
        search = calls[1]["args"]
        self.assertIn("--author", search)
        self.assertIn("@me", search)
        self.assertIn(">=2026-11-05", search)
        self.assertIn("50", search)
        self.assertIn("number,repository,state,title,updatedAt,url", search)

    def test_github_default_since_is_yesterday(self):
        self.gh_stub()
        result = self.run_script(GITHUB)
        self.assertEqual(result.returncode, 0, result.stderr)
        yesterday = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).date()
        self.assertIn(">=" + yesterday.isoformat(), self.calls("gh")[1]["args"])

    def test_github_auth_failure_stops_before_search(self):
        self.gh_stub(auth_ok=False)
        result = self.run_script(GITHUB, "2026-11-05")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gh auth login", result.stderr)
        self.assertEqual([c["args"][0] for c in self.calls("gh")], ["auth"])

    def test_github_detail_failure_stops_collection(self):
        self.gh_stub(detail_ok=False)
        result = self.run_script(GITHUB, "2026-11-05")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("activity collection stopped", result.stderr)
        self.assertIn("example/project#7", result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertEqual([c["args"][0] for c in self.calls("gh")], ["auth", "search", "pr"])

    # Jira helper -------------------------------------------------------

    def jira_stubs(self, keychain_ok=True):
        secret = json.dumps({"email": FAKE_EMAIL, "api_token": FAKE_TOKEN})
        self.stub(
            "security",
            f"""
            if {keychain_ok!r}:
                print({secret!r})
                sys.exit(0)
            print("The specified item could not be found in the keychain.", file=sys.stderr)
            sys.exit(44)
            """,
        )
        self.stub(
            "curl",
            """
            print(json.dumps({"issues": [
                {"key": "EX-1", "fields": {"summary": "Labelled work", "status": {"name": "In Progress"},
                 "updated": "2026-11-05T09:00:00.000+0000", "issuetype": {"name": "Task"},
                 "labels": ["this-week"]}},
                {"key": "EX-2", "fields": {"summary": "Unlabelled", "status": {"name": "Done"},
                 "updated": "2026-11-04T09:00:00.000+0000", "issuetype": {"name": "Bug"}}}]}))
            """,
        )

    def test_jira_search_keeps_the_secret_on_stdin(self):
        self.jira_stubs()
        result = self.run_script(
            JIRA, "2", "example.atlassian.net", env={"DIGITS_JIRA_PRIORITY_LABEL": "this-week"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        issues = {row["key"]: row for row in json.loads(result.stdout)}
        self.assertEqual(
            issues["EX-1"],
            {"key": "EX-1", "summary": "Labelled work", "status": "In Progress",
             "updated": "2026-11-05T09:00:00.000+0000", "type": "Task", "priority": True},
        )
        self.assertFalse(issues["EX-2"]["priority"])
        curl = self.calls("curl")
        self.assertEqual(len(curl), 1)
        args = curl[0]["args"]
        self.assertIn("https://example.atlassian.net/rest/api/3/search/jql", args)
        self.assertIn("-G", args)
        joined = " ".join(args)
        self.assertIn('labels = "this-week" AND statusCategory != Done', joined)
        self.assertIn("updated >= -2d", joined)
        self.assertIn("maxResults=30", args)
        self.assertIn("fields=summary,status,updated,issuetype,labels", args)
        for call in self.calls():
            self.assertNotIn(FAKE_TOKEN, " ".join(call["args"]))
        self.assertNotIn(FAKE_TOKEN, result.stdout)
        self.assertNotIn(FAKE_TOKEN, result.stderr)
        self.assertIn(f"{FAKE_EMAIL}:{FAKE_TOKEN}", curl[0]["stdin"])

    def test_jira_site_is_required_and_label_optional(self):
        self.jira_stubs()
        result = self.run_script(JIRA, "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no Jira site configured", result.stderr)
        self.assertEqual(self.calls("curl"), [])

        result = self.run_script(JIRA, env={"DIGITS_JIRA_SITE": "example.atlassian.net"})
        self.assertEqual(result.returncode, 0, result.stderr)
        args = " ".join(self.calls("curl")[0]["args"])
        self.assertNotIn("labels =", args)
        self.assertIn("assignee = currentUser() AND updated >= -1d ORDER BY updated DESC", args)
        self.assertTrue(all(not row["priority"] for row in json.loads(result.stdout)))

    def test_jira_missing_keychain_item(self):
        self.jira_stubs(keychain_ok=False)
        result = self.run_script(JIRA, "1", "example.atlassian.net")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no Jira credentials", result.stderr)
        self.assertIn("digits-standup-jira", result.stderr)
        self.assertEqual(self.calls("curl"), [])

    def test_jira_incomplete_keychain_json(self):
        self.stub("security", 'print(json.dumps({"email": "someone@example.com"}))')
        self.stub("curl", "")
        result = self.run_script(JIRA, "1", "example.atlassian.net")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls("curl"), [])

    def test_jira_rejects_bad_inputs_before_any_access(self):
        self.jira_stubs()
        cases = [
            (("1d", "example.atlassian.net"), {}),
            (("1", "https://example.atlassian.net"), {}),
            (("1", "example.atlassian.net/jira"), {}),
            (("1", "example.atlassian.net"), {"DIGITS_JIRA_PRIORITY_LABEL": "this week"}),
        ]
        for args, env in cases:
            with self.subTest(args=args, env=env):
                result = self.run_script(JIRA, *args, env=env)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.calls(), [])

    # Scheduled runner --------------------------------------------------

    def runner_stubs(self, copilot_body):
        self.stub("copilot", copilot_body)
        self.stub("pbcopy", "sys.stdin.read()")
        self.stub("osascript", "")

    @staticmethod
    def today(zone="UTC"):
        out = subprocess.run(
            ["date", "+%Y-%m-%d"], env={"TZ": zone, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    WRITING_COPILOT = """
        prompt = args[args.index("-p") + 1]
        draft = os.environ["EXPECTED_DRAFT"]
        assert draft in prompt, prompt
        assert not os.path.lexists(draft), draft
        assert "--allow-all-tools" in args and "--allow-all-urls" in args
        with open(draft, "w") as handle:
            handle.write("**Yesterday**\\n- In Review — repo #1: stub\\n")
        print("Saved to: " + draft)
        """

    def test_existing_draft_is_preserved(self):
        self.runner_stubs("sys.exit(0)")
        out = self.home / ".local" / "state" / "digits" / "standup"
        out.mkdir(parents=True)
        draft = out / (self.today() + ".md")
        draft.write_text("keep me\n")
        result = self.run_script(RUNNER)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertEqual(draft.read_text(), "keep me\n")
        self.assertEqual(self.calls("copilot"), [])

    def test_reply_is_kept_out_of_the_draft(self):
        self.runner_stubs(self.WRITING_COPILOT)
        out = self.home / ".local" / "state" / "digits" / "standup"
        draft = out / (self.today() + ".md")
        result = self.run_script(RUNNER, env={"EXPECTED_DRAFT": str(draft)})
        self.assertEqual(result.returncode, 0, result.stderr + self.read_log(out))
        self.assertEqual([p.name for p in out.glob("*.md")], [draft.name])
        self.assertEqual(draft.read_text(), "**Yesterday**\n- In Review — repo #1: stub\n")
        log = (out / (self.today() + ".log")).read_text()
        self.assertIn("Saved to:", log)
        self.assertIn("Draft saved to: " + str(draft), log)
        self.assertEqual(len(self.calls("pbcopy")), 1)
        self.assertEqual(len(self.calls("osascript")), 1)
        prompt = self.calls("copilot")[0]["args"]
        self.assertIn("/digits:standup-update", " ".join(prompt))
        self.assertIn(str(out / "copilot-logs"), prompt)

    def test_missing_draft_fails(self):
        self.runner_stubs("print('I could not save anything')")
        out = self.home / ".local" / "state" / "digits" / "standup"
        result = self.run_script(RUNNER)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(out.glob("*.md")), [])
        self.assertIn("no nonempty regular draft saved", (out / (self.today() + ".log")).read_text())
        self.assertEqual(self.calls("pbcopy"), [])

    def test_copilot_failure_fails_the_run(self):
        self.runner_stubs("sys.exit(3)")
        result = self.run_script(RUNNER)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls("pbcopy"), [])

    def test_output_dir_and_timezone_are_configurable(self):
        self.runner_stubs(self.WRITING_COPILOT)
        out = Path(self.tmp.name).resolve() / "custom drafts"
        zone = "Pacific/Kiritimati"
        draft = out / (self.today(zone) + ".md")
        result = self.run_script(
            RUNNER,
            env={"DIGITS_STANDUP_DIR": str(out), "DIGITS_STANDUP_TZ": zone, "EXPECTED_DRAFT": str(draft)},
        )
        self.assertEqual(result.returncode, 0, result.stderr + self.read_log(out))
        self.assertTrue(draft.is_file())
        self.assertFalse((self.home / ".local" / "state" / "digits" / "standup").exists())

    def test_dangling_symlink_draft_is_refused(self):
        self.runner_stubs("sys.exit(0)")
        out = self.home / ".local" / "state" / "digits" / "standup"
        out.mkdir(parents=True)
        draft = out / (self.today() + ".md")
        draft.symlink_to(out / "nowhere.md")
        result = self.run_script(RUNNER)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertTrue(draft.is_symlink())
        self.assertFalse((out / "nowhere.md").exists())
        self.assertEqual(self.calls("copilot"), [])

    @staticmethod
    def read_log(out):
        logs = list(Path(out).glob("*.log"))
        return logs[0].read_text() if logs else ""

    def test_helpers_are_executable_and_parse(self):
        for script in (GITHUB, JIRA, RUNNER):
            with self.subTest(script=script.name):
                self.assertTrue(os.stat(script).st_mode & stat.S_IXUSR)
                check = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stderr)


if __name__ == "__main__":
    unittest.main()

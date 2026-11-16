"""Tests for scripts/check_secrets.py."""

import contextlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_secrets as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_REGEX = r"(^|/)(\.git|\.venv|__pycache__|node_modules)(/|$)"


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class SecretGuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="digits-secrets-")))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        home = self.tmp / "home"
        home.mkdir()
        env = mock.patch.dict(
            os.environ,
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CEILING_DIRECTORIES": str(self.tmp),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        root_patch = mock.patch.object(guard, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def stub_index(self):
        patcher = mock.patch.object(guard, "require_index_match")
        stub = patcher.start()
        self.addCleanup(patcher.stop)
        return stub

    def stub_runner(self, **kwargs):
        patcher = mock.patch.object(guard.subprocess, "run", **kwargs)
        runner = patcher.start()
        self.addCleanup(patcher.stop)
        return runner

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = guard.main()
        return status, out.getvalue(), err.getvalue()


class StubbedScannerTests(SecretGuardTestCase):
    def test_missing_scanner_is_not_success(self):
        self.stub_index()
        self.stub_runner(side_effect=FileNotFoundError(2, "No such file", "detect-secrets"))
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("detect-secrets", err)
        self.assertIn("requirements-dev.txt", err)
        self.assertEqual(out, "")

    def test_network_verification_is_disabled(self):
        self.stub_index()
        runner = self.stub_runner(return_value=completed(stdout='{"results": {}}'))
        status, out, err = self.run_main()
        self.assertEqual(status, 0, err)
        self.assertIn("--no-verify", runner.call_args[0][0])

    def test_scanner_arguments_and_working_directory(self):
        index = self.stub_index()
        runner = self.stub_runner(return_value=completed(stdout='{"results": {}}'))
        self.run_main()
        index.assert_called_once_with(self.root)
        args, kwargs = runner.call_args
        self.assertEqual(
            args[0],
            [
                "detect-secrets",
                "scan",
                "--no-verify",
                "--all-files",
                "--exclude-files",
                EXCLUDE_REGEX,
            ],
        )
        self.assertEqual(Path(kwargs["cwd"]), self.root)
        self.assertNotIn("--baseline", args[0])

    def test_scanner_failure_is_not_success(self):
        self.stub_index()
        self.stub_runner(return_value=completed(returncode=2, stderr="boom"))
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("no passing result is claimed", err)
        self.assertNotIn("boom", err)
        self.assertEqual(out, "")

    def test_unparseable_output_is_not_success(self):
        self.stub_index()
        self.stub_runner(return_value=completed(stdout="not json"))
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("no passing result is claimed", err)
        self.assertEqual(out, "")

    def test_finding_format_hides_the_hash(self):
        self.stub_index()
        hashed = secrets.token_hex(20)
        payload = {
            "results": {
                "x.py": [
                    {
                        "type": "Secret Keyword",
                        "filename": "x.py",
                        "hashed_secret": hashed,
                        "is_verified": False,
                        "line_number": 3,
                    }
                ]
            }
        }
        self.stub_runner(return_value=completed(stdout=json.dumps(payload)))
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(err, "x.py:3: Secret Keyword\n")
        self.assertNotIn(hashed, out + err)
        self.assertEqual(out, "")

    def test_findings_follow_scanner_order(self):
        self.stub_index()
        payload = {
            "results": {
                "b.txt": [
                    {"type": "Hex High Entropy String", "line_number": 9},
                    {"type": "Secret Keyword", "line_number": 2},
                ],
                "a.txt": [{"type": "Private Key", "line_number": 1}],
            }
        }
        self.stub_runner(return_value=completed(stdout=json.dumps(payload)))
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(
            err.splitlines(),
            [
                "b.txt:9: Hex High Entropy String",
                "b.txt:2: Secret Keyword",
                "a.txt:1: Private Key",
            ],
        )

    def test_success_message(self):
        self.stub_index()
        self.stub_runner(return_value=completed(stdout='{"results": {}}'))
        status, out, err = self.run_main()
        self.assertEqual(status, 0)
        self.assertIn("passed", out)
        self.assertIn("manual review is still required", out)
        self.assertEqual(err, "")

    def test_index_failure_stops_before_scanning(self):
        runner = self.stub_runner(return_value=completed(stdout='{"results": {}}'))
        with mock.patch.object(
            guard, "require_index_match", side_effect=RuntimeError("Could not compare x")
        ):
            status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("Could not compare", err)
        runner.assert_not_called()


class DirectExecutionTests(unittest.TestCase):
    def test_script_run_directly_uses_the_repository_index_check(self):
        tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="digits-direct-")))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        (tmp / "scripts").mkdir()
        for name in ("check_repository.py", "check_secrets.py"):
            shutil.copy2(str(REPO_ROOT / "scripts" / name), str(tmp / "scripts" / name))
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp.parent))
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "scripts/check_secrets.py"],
            cwd=str(tmp),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not compare", result.stderr)
        self.assertEqual(result.stdout, "")


@unittest.skipIf(
    shutil.which("detect-secrets") is None,
    "detect-secrets is not on PATH; install requirements-dev.txt in a virtual environment",
)
class RealScannerTests(SecretGuardTestCase):
    def git(self, *args):
        subprocess.run(
            ["git"] + list(args),
            cwd=str(self.root),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_real_finding_is_reported_without_its_value(self):
        value = secrets.token_hex(32)
        (self.root / "bad.py").write_text(
            "password = " + json.dumps(value) + "\n", encoding="utf-8"
        )
        self.git("init", "-q")
        self.git("add", "bad.py")
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("bad.py", err)
        self.assertNotIn(value, out + err)
        self.assertNotIn(value[:16], out + err)


if __name__ == "__main__":
    unittest.main()

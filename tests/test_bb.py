#!/usr/bin/env python3
"""Tests for bb v0.1.0."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import bb


def _pass_step(name="t1", ms=100):
    return {
        "name": name,
        "command": name,
        "status": "pass",
        "exit_code": 0,
        "duration_ms": ms,
        "output": "",
        "error": "",
    }


def _fail_step(name="t2", ms=200, error="boom"):
    return {
        "name": name,
        "command": name,
        "status": "fail",
        "exit_code": 1,
        "duration_ms": ms,
        "output": "",
        "error": error,
    }


def _skip_step(name="t3", error="not found on PATH"):
    return {
        "name": name,
        "command": name,
        "status": "skipped",
        "exit_code": None,
        "duration_ms": 0,
        "output": "",
        "error": error,
    }


class TestValidateCommand(unittest.TestCase):
    def test_accepts_plain_names(self):
        for cmd in ("ruff", "config-drift", "python3", "mdguard"):
            self.assertTrue(bb.validate_command(cmd))

    def test_accepts_paths(self):
        self.assertTrue(bb.validate_command("/usr/bin/python"))
        self.assertTrue(bb.validate_command("C:\\Python\\python.exe"))
        self.assertTrue(bb.validate_command("./local_tool"))

    def test_rejects_metacharacters(self):
        bad = [
            "ruff; rm -rf /",
            "ruff | cat",
            "ruff && evil",
            "ruff `whoami`",
            "$(evil)",
            "ruff > /etc/passwd",
            "ruff check",
            "",
        ]
        for cmd in bad:
            self.assertFalse(bb.validate_command(cmd), cmd)


class TestValidateRepoPath(unittest.TestCase):
    def test_valid_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, resolved = bb.validate_repo_path(tmp)
            self.assertTrue(ok)
            self.assertEqual(Path(resolved), Path(tmp).resolve())

    def test_missing_path(self):
        ok, err = bb.validate_repo_path("/nonexistent/xyz/abc")
        self.assertFalse(ok)
        self.assertIn("cannot resolve", err)

    def test_file_is_not_dir(self):
        fd, path = tempfile.mkstemp()
        try:
            os.close(fd)
            ok, err = bb.validate_repo_path(path)
            self.assertFalse(ok)
            self.assertIn("not a directory", err)
        finally:
            os.unlink(path)

    def test_traversal_is_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "sub"
            sub.mkdir()
            ok, resolved = bb.validate_repo_path(str(sub / ".." / "sub"))
            self.assertTrue(ok)
            self.assertEqual(Path(resolved), sub.resolve())


class TestToolAvailable(unittest.TestCase):
    def test_found(self):
        with patch("shutil.which", return_value="/usr/bin/x"):
            self.assertTrue(bb.tool_available("x"))

    def test_missing(self):
        with patch("shutil.which", return_value=None):
            self.assertFalse(bb.tool_available("x"))


class TestToolVersion(unittest.TestCase):
    def test_returns_none_when_missing(self):
        with patch("shutil.which", return_value=None):
            self.assertIsNone(bb.tool_version("nope"))

    def test_reads_stdout_first_line(self):
        self.assertIsNotNone(bb.tool_version(sys.executable))

    def test_handles_timeout(self):
        with patch("shutil.which", return_value="/usr/bin/x"):
            exc = subprocess.TimeoutExpired(cmd="x", timeout=1)
            with patch("subprocess.run", side_effect=exc):
                self.assertIsNone(bb.tool_version("x"))

    def test_handles_oserror(self):
        with patch("shutil.which", return_value="/usr/bin/x"):
            with patch("subprocess.run", side_effect=OSError("nope")):
                self.assertIsNone(bb.tool_version("x"))

    def test_falls_back_to_stderr(self):
        fake = subprocess.CompletedProcess(
            args=["x"], returncode=0, stdout="", stderr="v1.2.3\nmore"
        )
        with patch("shutil.which", return_value="/usr/bin/x"):
            with patch("subprocess.run", return_value=fake):
                self.assertEqual(bb.tool_version("x"), "v1.2.3")

    def test_empty_output_returns_none(self):
        fake = subprocess.CompletedProcess(
            args=["x"], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/x"):
            with patch("subprocess.run", return_value=fake):
                self.assertIsNone(bb.tool_version("x"))


class TestLoadConfig(unittest.TestCase):
    def test_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                self.assertEqual(bb.load_config(), {})
            finally:
                os.chdir(cwd)

    def test_explicit_missing_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            bb.load_config("/nonexistent/bb.json")
        self.assertEqual(ctx.exception.code, 2)

    def test_loads_bb_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("bb.json").write_text(json.dumps({"preflight": ["a"]}))
                self.assertEqual(bb.load_config()["preflight"], ["a"])
            finally:
                os.chdir(cwd)

    def test_loads_dot_billybox_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path(".billybox.json").write_text(json.dumps({"preflight": ["b"]}))
                self.assertEqual(bb.load_config()["preflight"], ["b"])
            finally:
                os.chdir(cwd)

    def test_bb_json_wins_over_billybox(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("bb.json").write_text(json.dumps({"preflight": ["first"]}))
                Path(".billybox.json").write_text(json.dumps({"preflight": ["second"]}))
                self.assertEqual(bb.load_config()["preflight"], ["first"])
            finally:
                os.chdir(cwd)

    def test_invalid_json_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("bb.json").write_text("{nope")
                with self.assertRaises(SystemExit) as ctx:
                    bb.load_config()
                self.assertEqual(ctx.exception.code, 2)
            finally:
                os.chdir(cwd)

    def test_non_object_root_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("bb.json").write_text("[1, 2, 3]")
                with self.assertRaises(SystemExit) as ctx:
                    bb.load_config()
                self.assertEqual(ctx.exception.code, 2)
            finally:
                os.chdir(cwd)


class TestDefaultConfig(unittest.TestCase):
    def test_has_expected_keys(self):
        cfg = bb.get_default_config()
        for key in ("preflight", "timeout_seconds", "mockroute", "commitlog"):
            self.assertIn(key, cfg)

    def test_preflight_has_five_steps(self):
        self.assertEqual(len(bb.get_default_config()["preflight"]), 5)

    def test_timeout_is_120(self):
        self.assertEqual(bb.get_default_config()["timeout_seconds"], 120)


class TestRunStep(unittest.TestCase):
    def test_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = bb.run_step(f'"{sys.executable}" -c "print(1)"', tmp, 20)
            self.assertEqual(r["status"], "pass")
            self.assertEqual(r["exit_code"], 0)

    def test_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = bb.run_step(f'"{sys.executable}" -c "raise SystemExit(3)"', tmp, 20)
            self.assertEqual(r["status"], "fail")
            self.assertEqual(r["exit_code"], 3)

    def test_missing_tool_is_skipped(self):
        r = bb.run_step("definitely-not-a-real-tool-xyz scan", ".", 10)
        self.assertEqual(r["status"], "skipped")
        self.assertIn("not found on PATH", r["error"])

    def test_injection_rejected(self):
        r = bb.run_step("evil;rm -rf /", ".", 10)
        self.assertEqual(r["status"], "skipped")
        self.assertIn("unsafe characters", r["error"])

    def test_empty_command_skipped(self):
        r = bb.run_step("   ", ".", 10)
        self.assertEqual(r["status"], "skipped")
        self.assertIn("empty command", r["error"])

    def test_unparseable_command_skipped(self):
        r = bb.run_step('foo "unclosed', ".", 10)
        self.assertEqual(r["status"], "skipped")
        self.assertIn("unparseable", r["error"])

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = "import time; time.sleep(10)"
            r = bb.run_step(f'"{sys.executable}" -c "{script}"', tmp, 1)
            self.assertEqual(r["status"], "fail")
            self.assertIn("Timed out", r["error"])

    def test_oserror(self):
        with patch("shutil.which", return_value="/usr/bin/x"):
            with patch("subprocess.run", side_effect=OSError("denied")):
                r = bb.run_step("x", ".", 10)
                self.assertEqual(r["status"], "fail")
                self.assertIn("denied", r["error"])

    def test_verbose_appends_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = "import sys; sys.stderr.write('warned')"
            r = bb.run_step(f'"{sys.executable}" -c "{script}"', tmp, 20, verbose=True)
            self.assertIn("warned", r["output"])

    def test_name_is_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = bb.run_step(f'"{sys.executable}" -c "pass"', tmp, 20)
            self.assertEqual(r["name"], Path(sys.executable).name)

    def test_command_preserved(self):
        r = bb.run_step("not-real-xyz --flag", ".", 10)
        self.assertEqual(r["command"], "not-real-xyz --flag")


class TestSummarize(unittest.TestCase):
    def test_counts(self):
        c = bb.summarize([_pass_step(), _fail_step(), _skip_step()])
        self.assertEqual(c["total"], 3)
        self.assertEqual(c["passed"], 1)
        self.assertEqual(c["failed"], 1)
        self.assertEqual(c["skipped"], 1)

    def test_empty(self):
        c = bb.summarize([])
        self.assertEqual(c, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})


class TestFormatTerminal(unittest.TestCase):
    def test_basic(self):
        out = bb.format_terminal(
            [_pass_step("alpha"), _fail_step("beta")], "/repo", no_color=True
        )
        self.assertIn("BB PREFLIGHT", out)
        self.assertIn("alpha", out)
        self.assertIn("beta", out)
        self.assertIn("PASS", out)
        self.assertIn("FAIL", out)
        self.assertIn("1 passed, 1 failed, 0 skipped", out)

    def test_no_color_has_no_ansi(self):
        out = bb.format_terminal([_pass_step()], "/repo", no_color=True)
        self.assertNotIn("\033[", out)

    def test_color_has_ansi(self):
        out = bb.format_terminal([_pass_step()], "/repo", no_color=False)
        self.assertIn("\033[", out)

    def test_skip_shows_reason(self):
        out = bb.format_terminal(
            [_skip_step("gamma", "not found on PATH")], "/repo", no_color=True
        )
        self.assertIn("SKIP", out)
        self.assertNotIn("SKIPPED", out)
        self.assertIn("not found on PATH", out)

    def test_fail_shows_first_error_line(self):
        step = _fail_step("d", error="line1\nline2")
        out = bb.format_terminal([step], "/repo", no_color=True)
        self.assertIn("line1", out)
        self.assertNotIn("line2", out)

    def test_zero_duration_dash(self):
        out = bb.format_terminal([_skip_step()], "/repo", no_color=True)
        self.assertIn("─", out)

    def test_verbose_shows_output(self):
        step = _pass_step()
        step["output"] = "hello world"
        out = bb.format_terminal([step], "/repo", no_color=True, verbose=True)
        self.assertIn("hello world", out)

    def test_empty_results(self):
        out = bb.format_terminal([], "/repo", no_color=True)
        self.assertIn("0 passed, 0 failed, 0 skipped", out)

    def test_custom_title(self):
        out = bb.format_terminal([], "/repo", title="CUSTOM", no_color=True)
        self.assertIn("CUSTOM", out)

    def test_color_skip_branch(self):
        out = bb.format_terminal([_skip_step()], "/repo", no_color=False)
        self.assertIn("\033[33m", out)

    def test_color_fail_branch(self):
        out = bb.format_terminal([_fail_step()], "/repo", no_color=False)
        self.assertIn("\033[31m", out)


class TestFormatJson(unittest.TestCase):
    def test_shape(self):
        raw = bb.format_json([_pass_step(), _fail_step()], ".", 1)
        data = json.loads(raw)
        self.assertEqual(data["summary"]["total"], 2)
        self.assertEqual(data["summary"]["passed"], 1)
        self.assertEqual(data["summary"]["failed"], 1)
        self.assertEqual(data["exit_code"], 1)
        self.assertEqual(data["bb_version"], bb.__version__)
        self.assertIn("timestamp", data)
        self.assertEqual(len(data["steps"]), 2)

    def test_empty(self):
        data = json.loads(bb.format_json([], ".", 0))
        self.assertEqual(data["summary"]["total"], 0)
        self.assertEqual(data["exit_code"], 0)

    def test_repo_is_absolute(self):
        data = json.loads(bb.format_json([], ".", 0))
        self.assertTrue(Path(data["repo"]).is_absolute())


class TestFormatDoctor(unittest.TestCase):
    def _rows(self):
        return [
            {"name": "ctxpack", "installed": True, "path": "/x", "version": "1.0.0"},
            {"name": "mockroute", "installed": False, "path": None, "version": None},
        ]

    def test_terminal_no_color(self):
        out = bb.format_doctor_terminal(self._rows(), no_color=True)
        self.assertIn("BB DOCTOR", out)
        self.assertIn("ctxpack", out)
        self.assertIn("OK", out)
        self.assertIn("MISSING", out)
        self.assertIn("1 installed, 1 missing", out)
        self.assertNotIn("\033[", out)

    def test_terminal_color(self):
        out = bb.format_doctor_terminal(self._rows(), no_color=False)
        self.assertIn("\033[", out)

    def test_terminal_shows_python(self):
        out = bb.format_doctor_terminal(self._rows(), no_color=True)
        self.assertIn("Python:", out)

    def test_json_shape(self):
        data = json.loads(bb.format_doctor_json(self._rows(), 0))
        self.assertEqual(data["summary"]["total"], 2)
        self.assertEqual(data["summary"]["installed"], 1)
        self.assertEqual(data["summary"]["missing"], 1)
        self.assertEqual(data["bb_version"], bb.__version__)
        self.assertEqual(data["exit_code"], 0)
        self.assertIn("python_version", data)


class TestCmdDoctor(unittest.TestCase):
    def _args(self, **kw):
        base = {"json": False, "no_color": True, "strict": False}
        base.update(kw)
        return argparse.Namespace(**base)

    def test_returns_zero_when_not_strict(self):
        with patch("shutil.which", return_value=None):
            self.assertEqual(bb.cmd_doctor(self._args()), 0)

    def test_strict_fails_when_missing(self):
        with patch("shutil.which", return_value=None):
            self.assertEqual(bb.cmd_doctor(self._args(strict=True)), 1)

    def test_strict_passes_when_all_installed(self):
        with patch("shutil.which", return_value="/usr/bin/x"):
            with patch.object(bb, "tool_version", return_value="1.0.0"):
                self.assertEqual(bb.cmd_doctor(self._args(strict=True)), 0)

    def test_json_output(self):
        with patch("shutil.which", return_value=None):
            self.assertEqual(bb.cmd_doctor(self._args(json=True)), 0)


class TestCmdRun(unittest.TestCase):
    def test_rejects_unsafe_tool(self):
        args = argparse.Namespace(tool="evil;rm", args=[])
        self.assertEqual(bb.cmd_run(args), 2)

    def test_missing_tool_returns_2(self):
        args = argparse.Namespace(tool="not-a-real-tool-xyz", args=[])
        self.assertEqual(bb.cmd_run(args), 2)

    def test_passthrough_exit_code(self):
        args = argparse.Namespace(
            tool=sys.executable, args=["-c", "raise SystemExit(7)"]
        )
        self.assertEqual(bb.cmd_run(args), 7)

    def test_success_returns_zero(self):
        args = argparse.Namespace(tool=sys.executable, args=["-c", "pass"])
        self.assertEqual(bb.cmd_run(args), 0)

    def test_oserror_returns_2(self):
        args = argparse.Namespace(tool="python", args=[])
        with patch("shutil.which", return_value="/usr/bin/python"):
            with patch("subprocess.run", side_effect=OSError("nope")):
                self.assertEqual(bb.cmd_run(args), 2)


class TestCmdPreflight(unittest.TestCase):
    def _args(self, **kw):
        base = {
            "config": None,
            "repo": None,
            "only": None,
            "json": False,
            "no_color": True,
            "fail_fast": False,
            "timeout": 10,
            "verbose": False,
        }
        base.update(kw)
        return argparse.Namespace(**base)

    def _write_config(self, tmp, steps):
        path = Path(tmp) / "bb.json"
        path.write_text(json.dumps({"preflight": steps, "timeout_seconds": 10}))
        return str(path)

    def test_all_skipped_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, ["not-a-real-tool-xyz check"])
            rc = bb.cmd_preflight(self._args(config=cfg, repo=tmp))
            self.assertEqual(rc, 0)

    def test_failing_step_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            step = f'"{sys.executable}" -c "raise SystemExit(1)"'
            cfg = self._write_config(tmp, [step])
            rc = bb.cmd_preflight(self._args(config=cfg, repo=tmp))
            self.assertEqual(rc, 1)

    def test_passing_step_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, [f'"{sys.executable}" -c "pass"'])
            rc = bb.cmd_preflight(self._args(config=cfg, repo=tmp))
            self.assertEqual(rc, 0)

    def test_invalid_repo_returns_2(self):
        rc = bb.cmd_preflight(self._args(repo="/nonexistent/xyz"))
        self.assertEqual(rc, 2)

    def test_empty_preflight_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, [])
            rc = bb.cmd_preflight(self._args(config=cfg, repo=tmp))
            self.assertEqual(rc, 2)

    def test_non_string_step_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bb.json"
            path.write_text(json.dumps({"preflight": [123]}))
            rc = bb.cmd_preflight(self._args(config=str(path), repo=tmp))
            self.assertEqual(rc, 2)

    def test_only_filter_no_match_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, ["not-a-real-tool-xyz check"])
            rc = bb.cmd_preflight(self._args(config=cfg, repo=tmp, only=["nothing"]))
            self.assertEqual(rc, 2)

    def test_only_filter_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(
                tmp, ["not-a-real-tool-xyz check", "other-missing-tool run"]
            )
            rc = bb.cmd_preflight(
                self._args(config=cfg, repo=tmp, only=["not-a-real-tool-xyz"])
            )
            self.assertEqual(rc, 0)

    def test_fail_fast_stops_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            fail = f'"{sys.executable}" -c "raise SystemExit(1)"'
            cfg = self._write_config(tmp, [fail, fail])
            rc = bb.cmd_preflight(
                self._args(config=cfg, repo=tmp, fail_fast=True, json=True)
            )
            self.assertEqual(rc, 1)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, [f'"{sys.executable}" -c "pass"'])
            rc = bb.cmd_preflight(self._args(config=cfg, repo=tmp, json=True))
            self.assertEqual(rc, 0)

    def test_uses_defaults_without_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                rc = bb.cmd_preflight(self._args(repo=tmp))
                self.assertEqual(rc, 0)
            finally:
                os.chdir(cwd)

    def test_non_list_preflight_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bb.json"
            path.write_text(json.dumps({"preflight": "not-a-list"}))
            rc = bb.cmd_preflight(self._args(config=str(path), repo=tmp))
            self.assertEqual(rc, 2)


class TestCmdServe(unittest.TestCase):
    def _args(self, **kw):
        base = {"config": None, "routes": None, "port": None}
        base.update(kw)
        return argparse.Namespace(**base)

    def test_missing_mockroute_returns_2(self):
        with patch("shutil.which", return_value=None):
            self.assertEqual(bb.cmd_serve(self._args()), 2)

    def test_invalid_mockroute_section_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bb.json"
            path.write_text(json.dumps({"mockroute": "nope"}))
            self.assertEqual(bb.cmd_serve(self._args(config=str(path))), 2)

    def test_invokes_mockroute_with_defaults(self):
        fake = subprocess.CompletedProcess(args=["mockroute"], returncode=0)
        with patch("shutil.which", return_value="/usr/bin/mockroute"):
            with patch("subprocess.run", return_value=fake) as m:
                rc = bb.cmd_serve(self._args())
                self.assertEqual(rc, 0)
                cmd = m.call_args[0][0]
                self.assertEqual(cmd[0], "mockroute")
                self.assertIn("routes.json", cmd)
                self.assertIn("8000", cmd)

    def test_flag_overrides(self):
        fake = subprocess.CompletedProcess(args=["mockroute"], returncode=0)
        with patch("shutil.which", return_value="/usr/bin/mockroute"):
            with patch("subprocess.run", return_value=fake) as m:
                bb.cmd_serve(self._args(routes="custom.json", port=9999))
                cmd = m.call_args[0][0]
                self.assertIn("custom.json", cmd)
                self.assertIn("9999", cmd)

    def test_keyboard_interrupt_returns_zero(self):
        with patch("shutil.which", return_value="/usr/bin/mockroute"):
            with patch("subprocess.run", side_effect=KeyboardInterrupt):
                self.assertEqual(bb.cmd_serve(self._args()), 0)

    def test_oserror_returns_2(self):
        with patch("shutil.which", return_value="/usr/bin/mockroute"):
            with patch("subprocess.run", side_effect=OSError("nope")):
                self.assertEqual(bb.cmd_serve(self._args()), 2)


class TestCmdRelease(unittest.TestCase):
    def _args(self, **kw):
        base = {"config": None, "since": None, "format": None, "output": None}
        base.update(kw)
        return argparse.Namespace(**base)

    def test_missing_commitlog_returns_2(self):
        with patch("shutil.which", return_value=None):
            self.assertEqual(bb.cmd_release(self._args()), 2)

    def test_invalid_commitlog_section_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bb.json"
            path.write_text(json.dumps({"commitlog": []}))
            self.assertEqual(bb.cmd_release(self._args(config=str(path))), 2)

    def test_invokes_commitlog_with_defaults(self):
        fake = subprocess.CompletedProcess(args=["commitlog"], returncode=0)
        with patch("shutil.which", return_value="/usr/bin/commitlog"):
            with patch("subprocess.run", return_value=fake) as m:
                rc = bb.cmd_release(self._args())
                self.assertEqual(rc, 0)
                cmd = m.call_args[0][0]
                self.assertEqual(cmd[:2], ["commitlog", "generate"])
                self.assertIn("last_tag", cmd)
                self.assertIn("markdown", cmd)

    def test_output_flag_appended(self):
        fake = subprocess.CompletedProcess(args=["commitlog"], returncode=0)
        with patch("shutil.which", return_value="/usr/bin/commitlog"):
            with patch("subprocess.run", return_value=fake) as m:
                bb.cmd_release(self._args(output="NOTES.md"))
                cmd = m.call_args[0][0]
                self.assertIn("--output", cmd)
                self.assertIn("NOTES.md", cmd)

    def test_oserror_returns_2(self):
        with patch("shutil.which", return_value="/usr/bin/commitlog"):
            with patch("subprocess.run", side_effect=OSError("nope")):
                self.assertEqual(bb.cmd_release(self._args()), 2)


class TestCmdInit(unittest.TestCase):
    def test_creates_all_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                rc = bb.cmd_init(argparse.Namespace(force=False))
                self.assertEqual(rc, 0)
                for name in (
                    "bb.json",
                    "policy.json",
                    "routes.json",
                    "commitlog.json",
                    ".ctxignore",
                ):
                    self.assertTrue(Path(name).exists(), name)
            finally:
                os.chdir(cwd)

    def test_bb_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                bb.cmd_init(argparse.Namespace(force=False))
                data = json.loads(Path("bb.json").read_text())
                self.assertIn("preflight", data)
            finally:
                os.chdir(cwd)

    def test_skips_existing_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("bb.json").write_text('{"mine": true}')
                bb.cmd_init(argparse.Namespace(force=False))
                data = json.loads(Path("bb.json").read_text())
                self.assertIn("mine", data)
            finally:
                os.chdir(cwd)

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("bb.json").write_text('{"mine": true}')
                bb.cmd_init(argparse.Namespace(force=True))
                data = json.loads(Path("bb.json").read_text())
                self.assertNotIn("mine", data)
                self.assertIn("preflight", data)
            finally:
                os.chdir(cwd)

    def test_ctxignore_skipped_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path(".ctxignore").write_text("custom\n")
                bb.cmd_init(argparse.Namespace(force=False))
                self.assertEqual(Path(".ctxignore").read_text(), "custom\n")
            finally:
                os.chdir(cwd)


class TestTemplates(unittest.TestCase):
    def test_all_templates_json_serializable(self):
        for name, payload in bb.get_templates().items():
            self.assertIsInstance(json.dumps(payload), str, name)

    def test_ctxignore_template_non_empty(self):
        self.assertIn(".git/", bb.CTXIGNORE_TEMPLATE)


class TestCli(unittest.TestCase):
    def test_version(self):
        with self.assertRaises(SystemExit) as ctx:
            bb.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_no_command_exits_1(self):
        with self.assertRaises(SystemExit) as ctx:
            bb.main([])
        self.assertEqual(ctx.exception.code, 1)

    def test_doctor_via_main(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                bb.main(["doctor", "--no-color"])
            self.assertEqual(ctx.exception.code, 0)

    def test_doctor_strict_via_main(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                bb.main(["doctor", "--no-color", "--strict"])
            self.assertEqual(ctx.exception.code, 1)

    def test_init_via_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self.assertRaises(SystemExit) as ctx:
                    bb.main(["init"])
                self.assertEqual(ctx.exception.code, 0)
            finally:
                os.chdir(cwd)

    def test_parser_builds(self):
        parser = bb.build_parser()
        self.assertEqual(parser.prog, "bb")

    def test_handlers_cover_all_subcommands(self):
        expected = {"doctor", "run", "preflight", "serve", "release", "init"}
        self.assertEqual(set(bb.HANDLERS), expected)

    def test_billybox_tools_list(self):
        self.assertIn("ctxpack", bb.BILLYBOX_TOOLS)
        self.assertIn("fieldboard", bb.BILLYBOX_TOOLS)
        self.assertEqual(len(bb.BILLYBOX_TOOLS), 5)


if __name__ == "__main__":
    unittest.main()

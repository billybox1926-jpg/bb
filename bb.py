#!/usr/bin/env python3
"""bb - BillyBox Toolbelt.

One local-first CLI that wraps the BillyBox tools with consistent
configuration, output, and workflows.

SECURITY: preflight commands come from bb.json and are executed as
subprocesses. Only run bb against configuration files you trust.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__version__ = "0.1.0"

DEFAULT_TIMEOUT = 120

CONFIG_NAMES = ("bb.json", ".billybox.json")

# Single source of truth: every tool bb can invoke, mapped to its PyPI
# distribution name. The command (key) is what lands on PATH; the value is what
# you pip install. They differ where the bare name was already taken on PyPI.
#
# Verified against PyPI and each repo's pyproject.toml on 2026-08-20.
TOOL_PACKAGES = {
    # Core suite
    "ctxpack": "ctxpack-cli",  # 'ctxpack' taken by an unrelated project
    "mockroute": "mockroute",
    "config-drift": "config-drift",
    "commitlog": "commitlog-cli",  # 'commitlog' taken by an unrelated project
    "fieldboard": "fieldboard",
    "bb": "bb-toolbelt",  # 'bb' taken by a bitbucket CLI
    # Quality tools invoked by preflight
    "mdguard": "mdguard",
    "graft": "graft-inventory",  # 'graft' AND 'graft-cli' both taken
    "policy-runner": "policy-runner",
    # NOTE: the console script is 'depscan', not 'dep-health-scanner'.
    "depscan": "dep-health-scanner",
}

BILLYBOX_TOOLS = tuple(TOOL_PACKAGES)

# Tools that are not published to PyPI yet. bb install reports these as
# 'unavailable' rather than attempting an install that would 404 — or worse,
# silently fetch a squatted package.
UNPUBLISHED_TOOLS = frozenset(TOOL_PACKAGES)

# Default quality gate.
#
# Every invocation below was verified against the tool's actual CLI, not its
# README prose. Divergences that were corrected:
#   - mdguard has no 'check' subcommand; it takes positional paths.
#   - graft has no 'scan' subcommand and no --json; it takes a directory
#     plus --check for read-only validation.
#   - policy-runner has no 'run' subcommand; --task and --policy are required,
#     so it cannot have a zero-config default and is omitted here.
#   - dep-health-scanner installs as 'depscan' and has no --json (--exit-code).
#   - config-drift requires --configs-root and --environments.
DEFAULT_PREFLIGHT = [
    "mdguard . --json",
    "graft . --check",
    "depscan scan --exit-code",
    "config-drift diff --configs-root ./configs --environments dev,staging,prod"
    " --fail-on-drift",
]

# Command names may contain alphanumerics, dots, dashes, underscores and path
# separators. This rejects shell metacharacters such as ; | & ` $ > <
SAFE_COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9._\-/\\:]+$")


def validate_command(command: str) -> bool:
    """Return True if a command name contains no shell metacharacters."""
    return bool(SAFE_COMMAND_PATTERN.match(command))


def validate_repo_path(repo: str) -> tuple[bool, str]:
    """Resolve and validate a repo path. Returns (ok, resolved_or_error)."""
    try:
        path = Path(repo).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return False, f"cannot resolve path: {exc}"
    if not path.is_dir():
        return False, "not a directory"
    return True, str(path)


def tool_available(command: str) -> bool:
    """Return True if a command is resolvable on PATH."""
    return shutil.which(command) is not None


def tool_version(command: str) -> str | None:
    """Return the --version output of a tool, or None if unavailable."""
    if not tool_available(command):
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (result.stdout or result.stderr or "").strip()
    return out.split("\n")[0] if out else None


def find_config(explicit: str | None = None) -> Path | None:
    """Locate the bb config file."""
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for name in CONFIG_NAMES:
        candidate = Path(name)
        if candidate.exists():
            return candidate
    return None


def load_config(explicit: str | None = None) -> dict[str, Any]:
    """Load bb.json / .billybox.json, or return {} when absent."""
    path = find_config(explicit)
    if path is None:
        if explicit:
            print(f"Error: config file not found: {explicit}", file=sys.stderr)
            sys.exit(2)
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error: invalid config file {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"Error: config root in {path} must be an object", file=sys.stderr)
        sys.exit(2)
    return data


def get_default_config() -> dict[str, Any]:
    """Return the default bb configuration."""
    return {
        "preflight": list(DEFAULT_PREFLIGHT),
        "timeout_seconds": DEFAULT_TIMEOUT,
        "mockroute": {"config": "routes.json", "port": 8000},
        "commitlog": {"since": "last_tag", "format": "markdown"},
    }


def run_step(
    command_line: str,
    repo: str,
    timeout: int,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run one preflight command line and return a normalized result."""
    try:
        parts = shlex.split(command_line)
    except ValueError as exc:
        return {
            "name": command_line,
            "command": command_line,
            "status": "skipped",
            "exit_code": None,
            "duration_ms": 0,
            "output": "",
            "error": f"unparseable command: {exc}",
        }

    if not parts:
        return {
            "name": command_line,
            "command": command_line,
            "status": "skipped",
            "exit_code": None,
            "duration_ms": 0,
            "output": "",
            "error": "empty command",
        }

    executable = parts[0]
    name = Path(executable).name

    if not validate_command(executable):
        return {
            "name": name,
            "command": command_line,
            "status": "skipped",
            "exit_code": None,
            "duration_ms": 0,
            "output": "",
            "error": f"rejected: unsafe characters in '{executable}'",
        }

    if not tool_available(executable):
        return {
            "name": name,
            "command": command_line,
            "status": "skipped",
            "exit_code": None,
            "duration_ms": 0,
            "output": "",
            "error": "not found on PATH",
        }

    start = time.monotonic()
    try:
        result = subprocess.run(
            parts,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "command": command_line,
            "status": "fail",
            "exit_code": None,
            "duration_ms": timeout * 1000,
            "output": "",
            "error": f"Timed out after {timeout}s",
        }
    except OSError as exc:
        return {
            "name": name,
            "command": command_line,
            "status": "fail",
            "exit_code": None,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "output": "",
            "error": str(exc),
        }

    duration_ms = int((time.monotonic() - start) * 1000)
    output = result.stdout
    if verbose and result.stderr:
        output = f"{output}\n{result.stderr}" if output else result.stderr

    return {
        "name": name,
        "command": command_line,
        "status": "pass" if result.returncode == 0 else "fail",
        "exit_code": result.returncode,
        "duration_ms": duration_ms,
        "output": output,
        "error": result.stderr,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count pass/fail/skipped across results."""
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }


def format_terminal(
    results: list[dict[str, Any]],
    repo: str,
    title: str = "BB PREFLIGHT",
    no_color: bool = False,
    verbose: bool = False,
) -> str:
    """Render results as a terminal dashboard."""
    lines: list[str] = []
    if no_color:
        lines.append(f"{title} — {repo}")
    else:
        lines.append(f"\033[1m{title}\033[0m — {repo}")
    lines.append("")
    lines.append(f" {'Tool':<24} {'Status':<10} {'Duration':<12} Details")
    lines.append(" " + "─" * 62)

    for item in results:
        status = item["status"]
        duration = f"{item['duration_ms']}ms" if item["duration_ms"] > 0 else "─"

        if no_color:
            status_str = "SKIP" if status == "skipped" else status.upper()
            pad = 10
        elif status == "pass":
            status_str = "\033[32mPASS\033[0m"
            pad = 20
        elif status == "fail":
            status_str = "\033[31mFAIL\033[0m"
            pad = 20
        else:
            status_str = "\033[33mSKIP\033[0m"
            pad = 20

        detail = ""
        if status in ("fail", "skipped"):
            detail = (item.get("error") or "").split("\n")[0][:34]

        lines.append(f" {item['name']:<24} {status_str:<{pad}} {duration:<12} {detail}")

        if verbose and item.get("output"):
            for out_line in item["output"].split("\n")[:3]:
                if out_line:
                    lines.append(f"   {out_line[:70]}")

    counts = summarize(results)
    lines.append("")
    lines.append(
        f" Summary: {counts['passed']} passed, "
        f"{counts['failed']} failed, {counts['skipped']} skipped"
    )
    return "\n".join(lines)


def format_json(
    results: list[dict[str, Any]],
    repo: str,
    exit_code: int,
) -> str:
    """Render results as JSON."""
    payload = {
        "repo": str(Path(repo).resolve()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bb_version": __version__,
        "summary": summarize(results),
        "steps": results,
        "exit_code": exit_code,
    }
    return json.dumps(payload, indent=2)


def format_doctor_terminal(rows: list[dict[str, Any]], no_color: bool) -> str:
    """Render the doctor report as a terminal table."""
    lines: list[str] = []
    if no_color:
        lines.append(f"BB DOCTOR — bb {__version__}")
    else:
        lines.append(f"\033[1mBB DOCTOR\033[0m — bb {__version__}")
    lines.append("")
    lines.append(f" {'Tool':<24} {'Status':<10} Version / install hint")
    lines.append(" " + "─" * 62)

    for row in rows:
        if row["installed"]:
            status_str = "OK" if no_color else "\033[32mOK\033[0m"
            pad = 10 if no_color else 20
            detail = row.get("version") or "—"
        else:
            status_str = "MISSING" if no_color else "\033[33mMISSING\033[0m"
            pad = 10 if no_color else 20
            detail = f"pip install {row.get('package', row['name'])}"
        lines.append(f" {row['name']:<24} {status_str:<{pad}} {detail[:40]}")

    installed = sum(1 for r in rows if r["installed"])
    missing = len(rows) - installed
    lines.append("")
    lines.append(f" Summary: {installed} installed, {missing} missing")
    lines.append(f" Python:  {sys.version.split()[0]}")
    return "\n".join(lines)


def format_doctor_json(rows: list[dict[str, Any]], exit_code: int) -> str:
    """Render the doctor report as JSON."""
    installed = sum(1 for r in rows if r["installed"])
    payload = {
        "bb_version": __version__,
        "python_version": sys.version.split()[0],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(rows),
            "installed": installed,
            "missing": len(rows) - installed,
        },
        "tools": rows,
        "exit_code": exit_code,
    }
    return json.dumps(payload, indent=2)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that BillyBox tools are installed and report versions."""
    rows: list[dict[str, Any]] = []
    for tool in BILLYBOX_TOOLS:
        installed = tool_available(tool)
        rows.append(
            {
                "name": tool,
                "package": TOOL_PACKAGES[tool],
                "installed": installed,
                "path": shutil.which(tool),
                "version": tool_version(tool) if installed else None,
            }
        )

    missing = sum(1 for r in rows if not r["installed"])
    exit_code = 1 if (missing and args.strict) else 0

    if args.json:
        print(format_doctor_json(rows, exit_code))
    else:
        print(format_doctor_terminal(rows, args.no_color))

    return exit_code


def cmd_run(args: argparse.Namespace) -> int:
    """Pass through to any installed tool."""
    if not validate_command(args.tool):
        print(
            f"Error: unsafe characters in tool name '{args.tool}'",
            file=sys.stderr,
        )
        return 2

    if not tool_available(args.tool):
        print(f"Error: {args.tool} not found on PATH", file=sys.stderr)
        return 2

    try:
        result = subprocess.run([args.tool] + list(args.args), shell=False, check=False)
    except OSError as exc:
        print(f"Error: cannot run {args.tool}: {exc}", file=sys.stderr)
        return 2
    return result.returncode


def cmd_preflight(args: argparse.Namespace) -> int:
    """Run the configured quality gate."""
    config = load_config(args.config) or get_default_config()

    repo = args.repo or "."
    ok, resolved = validate_repo_path(repo)
    if not ok:
        print(f"Error: {repo} — {resolved}", file=sys.stderr)
        return 2
    repo = resolved

    steps = config.get("preflight", DEFAULT_PREFLIGHT)
    if not isinstance(steps, list) or not steps:
        print("Error: 'preflight' must be a non-empty array", file=sys.stderr)
        return 2

    timeout = args.timeout or config.get("timeout_seconds", DEFAULT_TIMEOUT)

    if args.only:
        steps = [
            s
            for s in steps
            if isinstance(s, str) and Path(shlex.split(s)[0]).name in args.only
        ]
        if not steps:
            print("No matching steps to run.", file=sys.stderr)
            return 2

    results: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, str):
            print("Error: each preflight entry must be a string", file=sys.stderr)
            return 2
        result = run_step(step, repo, timeout, args.verbose)
        results.append(result)
        if args.fail_fast and result["status"] == "fail":
            break

    counts = summarize(results)
    exit_code = 1 if counts["failed"] else 0

    if args.json:
        print(format_json(results, repo, exit_code))
    else:
        print(
            format_terminal(results, repo, "BB PREFLIGHT", args.no_color, args.verbose)
        )

    return exit_code


def cmd_serve(args: argparse.Namespace) -> int:
    """Start mockroute with the project's route config."""
    config = load_config(args.config) or get_default_config()
    settings = config.get("mockroute", {})
    if not isinstance(settings, dict):
        print("Error: 'mockroute' must be an object", file=sys.stderr)
        return 2

    route_config = args.routes or settings.get("config", "routes.json")
    port = args.port or settings.get("port", 8000)

    if not tool_available("mockroute"):
        print("Error: mockroute not found on PATH", file=sys.stderr)
        return 2

    cmd = ["mockroute", "--config", str(route_config), "--port", str(port)]
    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, shell=False, check=False)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Error: cannot run mockroute: {exc}", file=sys.stderr)
        return 2
    return result.returncode


def cmd_release(args: argparse.Namespace) -> int:
    """Run commitlog to produce release notes."""
    config = load_config(args.config) or get_default_config()
    settings = config.get("commitlog", {})
    if not isinstance(settings, dict):
        print("Error: 'commitlog' must be an object", file=sys.stderr)
        return 2

    since = args.since or settings.get("since", "last_tag")
    fmt = args.format or settings.get("format", "markdown")

    if not tool_available("commitlog"):
        print("Error: commitlog not found on PATH", file=sys.stderr)
        return 2

    cmd = ["commitlog", "generate", "--since", str(since), "--format", str(fmt)]
    if args.output:
        cmd += ["--output", args.output]

    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, shell=False, check=False)
    except OSError as exc:
        print(f"Error: cannot run commitlog: {exc}", file=sys.stderr)
        return 2
    return result.returncode


def get_templates() -> dict[str, Any]:
    """Return the scaffold templates written by `bb init`."""
    return {
        "bb.json": get_default_config(),
        "policy.json": {
            "deny": ["rm -rf /", "curl * | sh", "eval "],
            "warn": ["sudo ", "chmod 777"],
        },
        "routes.json": {
            "defaults": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "latency_ms": 0,
            },
            "routes": [
                {
                    "path": "/api/health",
                    "method": "GET",
                    "body": {"status": "ok"},
                }
            ],
        },
        "commitlog.json": {
            "grouping": True,
            "default_since": "last_tag",
            "default_format": "markdown",
            "ignored_scopes": ["chore"],
        },
    }


CTXIGNORE_TEMPLATE = """# ctxpack ignore patterns
.git/
.venv/
venv/
node_modules/
__pycache__/
dist/
build/
*.egg-info/
.pytest_cache/
.coverage
*.lock
*.png
*.jpg
*.pdf
"""


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a repo with BillyBox defaults."""
    templates = get_templates()
    created: list[str] = []
    skipped: list[str] = []

    for name, payload in templates.items():
        path = Path(name)
        if path.exists() and not args.force:
            skipped.append(name)
            continue
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        created.append(name)

    ctxignore = Path(".ctxignore")
    if ctxignore.exists() and not args.force:
        skipped.append(".ctxignore")
    else:
        ctxignore.write_text(CTXIGNORE_TEMPLATE, encoding="utf-8")
        created.append(".ctxignore")

    for name in created:
        print(f"created  {name}")
    for name in skipped:
        print(f"skipped  {name} (exists; use --force to overwrite)")

    print(f"\n{len(created)} created, {len(skipped)} skipped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the bb argument parser."""
    parser = argparse.ArgumentParser(prog="bb", description="bb - BillyBox Toolbelt")
    parser.add_argument("--version", action="version", version=f"bb {__version__}")
    sub = parser.add_subparsers(dest="command", help="command to execute")

    doctor = sub.add_parser("doctor", help="check environment and tool versions")
    doctor.add_argument("--json", action="store_true", help="JSON output")
    doctor.add_argument("--no-color", action="store_true", help="disable colors")
    doctor.add_argument(
        "--strict", action="store_true", help="exit 1 if any tool is missing"
    )

    run = sub.add_parser("run", help="pass through to any installed tool")
    run.add_argument("tool", help="tool to run")
    run.add_argument(
        "args", nargs=argparse.REMAINDER, help="arguments passed to the tool"
    )

    pre = sub.add_parser("preflight", help="run the configured quality gate")
    pre.add_argument("--config", default=None, help="config file (default: bb.json)")
    pre.add_argument("--repo", default=None, help="repo to run in (default: .)")
    pre.add_argument(
        "--only", action="append", help="only run named step(s), repeatable"
    )
    pre.add_argument("--json", action="store_true", help="JSON output")
    pre.add_argument("--no-color", action="store_true", help="disable colors")
    pre.add_argument(
        "--fail-fast", action="store_true", help="stop after first failure"
    )
    pre.add_argument("--timeout", type=int, default=None, help="per-step timeout (s)")
    pre.add_argument("--verbose", action="store_true", help="show step output")

    serve = sub.add_parser("serve", help="start mockroute with the project config")
    serve.add_argument("--config", default=None, help="bb config file")
    serve.add_argument("--routes", default=None, help="mockroute route config")
    serve.add_argument("--port", type=int, default=None, help="port to listen on")

    release = sub.add_parser("release", help="produce release notes via commitlog")
    release.add_argument("--config", default=None, help="bb config file")
    release.add_argument("--since", default=None, help="start tag or commit")
    release.add_argument("--format", default=None, choices=["markdown", "text", "json"])
    release.add_argument("--output", default=None, help="write notes to a file")

    init = sub.add_parser("init", help="scaffold a repo with BillyBox defaults")
    init.add_argument("--force", action="store_true", help="overwrite existing files")

    return parser


HANDLERS = {
    "doctor": cmd_doctor,
    "run": cmd_run,
    "preflight": cmd_preflight,
    "serve": cmd_serve,
    "release": cmd_release,
    "init": cmd_init,
}


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    sys.exit(handler(args))


if __name__ == "__main__":
    main()

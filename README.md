# bb — BillyBox Toolbelt

**One command to rule the toolbox.**

[![CI](https://github.com/billybox1926-jpg/bb/actions/workflows/ci.yml/badge.svg)](https://github.com/billybox1926-jpg/bb/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

`bb` is a single, local-first CLI that wraps the BillyBox tools with consistent
configuration, output, and workflows — so you stop remembering five commands
and five config formats.

## The Problem

You have five good tools, but using them means:

- remembering five commands
- configuring each one independently
- running them one at a time
- reading five different output formats

`bb` gives you one entry point, one config file, and one report.

## Quick Start

```bash
git clone https://github.com/billybox1926-jpg/bb.git
cd bb

# scaffold a project with BillyBox defaults
python bb.py init

# check which tools are installed
python bb.py doctor

# run the quality gate
python bb.py preflight
```

Install the `bb` entry point:

```bash
pip install .
bb --version
```

## Commands

| Command | What it does |
|---------|--------------|
| `bb init` | Scaffold `bb.json`, `.ctxignore`, `policy.json`, `routes.json`, `commitlog.json` |
| `bb doctor` | Check which BillyBox tools are installed and report versions |
| `bb preflight` | Run the configured quality gate; non-zero exit if any step fails |
| `bb serve` | Start `mockroute` with the project's route config |
| `bb release` | Run `commitlog` and produce release notes |
| `bb run <tool> [args...]` | Pass through to any installed tool |

## CLI Usage

```
bb doctor    [--json] [--no-color] [--strict]
bb run       <tool> [args...]
bb preflight [--config PATH] [--repo PATH] [--only NAME]
             [--json] [--no-color] [--fail-fast] [--timeout SEC] [--verbose]
bb serve     [--config PATH] [--routes PATH] [--port PORT]
bb release   [--config PATH] [--since TAG] [--format FMT] [--output PATH]
bb init      [--force]
```

## Configuration

`bb` reads `bb.json`, falling back to `.billybox.json`:

```json
{
  "preflight": [
    "mdguard check",
    "graft scan --json",
    "policy-runner run",
    "dep-health-scanner scan --json",
    "config-drift diff --fail-on-drift"
  ],
  "timeout_seconds": 120,
  "mockroute": {
    "config": "routes.json",
    "port": 8000
  },
  "commitlog": {
    "since": "last_tag",
    "format": "markdown"
  }
}
```

| Key | Meaning |
|-----|---------|
| `preflight` | Array of command lines to run as the quality gate |
| `timeout_seconds` | Per-step timeout (default 120) |
| `mockroute.config` | Route config passed to `bb serve` |
| `mockroute.port` | Port passed to `bb serve` |
| `commitlog.since` | Default `--since` for `bb release` |
| `commitlog.format` | Default `--format` for `bb release` |

If no config file exists, `bb` uses sensible defaults for the five BillyBox tools.

## Output

Terminal dashboard:

```
BB PREFLIGHT — /home/user/project

 Tool                     Status     Duration     Details
 ──────────────────────────────────────────────────────────────
 mdguard                  PASS       210ms
 graft                    PASS       380ms
 policy-runner            FAIL       1500ms       denied: rm -rf /
 dep-health-scanner       SKIP       ─            not found on PATH
 config-drift             PASS       900ms

 Summary: 3 passed, 1 failed, 1 skipped
```

JSON (`--json`):

```json
{
  "repo": "/home/user/project",
  "timestamp": "2026-08-20T10:00:00+00:00",
  "bb_version": "0.1.0",
  "summary": { "total": 5, "passed": 3, "failed": 1, "skipped": 1 },
  "steps": [
    {
      "name": "mdguard",
      "command": "mdguard check",
      "status": "pass",
      "exit_code": 0,
      "duration_ms": 210,
      "output": "...",
      "error": ""
    }
  ],
  "exit_code": 1
}
```

`bb doctor` reports installed tools and versions:

```
BB DOCTOR — bb 0.1.0

 Tool                     Status     Version
 ──────────────────────────────────────────────────────────────
 ctxpack                  OK         ctxpack 1.0.0
 mockroute                OK         mockroute 0.7.1
 config-drift             OK         config-drift 0.1.1
 commitlog                OK         commitlog 0.1.1
 fieldboard               MISSING    ─

 Summary: 4 installed, 1 missing
 Python:  3.12.0
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All steps passed (skipped steps do not fail the gate) |
| 1 | At least one step failed |
| 2 | Configuration error, invalid path, or tool not runnable |

Use it as a pre-push gate:

```bash
bb preflight || echo "Quality gates failed"
```

## Security Considerations

> [!WARNING]
> **`bb` executes the command lines listed in `bb.json`.** A malicious config
> can run arbitrary programs on your machine. Only run `bb` against
> configuration files you trust.

| Protection | Detail |
|------------|--------|
| **No shell** | Every subprocess runs with `shell=False`; command lines are tokenised with `shlex.split` and passed as a list, never interpolated into a shell string. |
| **Command validation** | The executable is validated against `^[A-Za-z0-9._\-/\\:]+$`. Anything containing `;`, `\|`, `&`, `` ` ``, `$`, `>` or a space is rejected and reported as `SKIP`. |
| **Path resolution** | `--repo` is resolved with `Path.resolve(strict=True)` and must be an existing directory. |
| **Timeouts** | Every step has a per-run timeout (default 120s), so a hung tool can't block your pipeline. |
| **Zero dependencies** | Standard library only — no supply-chain surface. |

Inspect an unfamiliar config before running it:

```bash
cat bb.json
bb preflight --json
```

## Related Tools

| Tool | Purpose |
|------|---------|
| [ctxpack](https://github.com/billybox1926-jpg/ctxpack) | Context window packaging |
| [mockroute](https://github.com/billybox1926-jpg/mockroute) | Local mock API server |
| [config-drift](https://github.com/billybox1926-jpg/config-drift) | Config drift detection |
| [commitlog](https://github.com/billybox1926-jpg/commitlog) | Release-note generator |
| [fieldboard](https://github.com/billybox1926-jpg/fieldboard) | Quality-tool dashboard |

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest pytest-cov ruff mypy pre-commit
pre-commit install

pytest tests/ -v
ruff check bb.py tests/test_bb.py
mypy bb.py --ignore-missing-imports
```

## License

MIT

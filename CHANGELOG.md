# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed
- **`bb doctor` / `bb preflight` registry mismatch.** `doctor` reported 5 tools
  while `DEFAULT_PREFLIGHT` invoked 5 *different* commands, 4 of which `doctor`
  could not see and `bb install` could not have installed. Both now derive from
  one `TOOL_PACKAGES` registry covering all 10 tools, and a test asserts every
  preflight step resolves to a registry key.
- **Invalid default preflight invocations.** Each was verified against the
  tool's real CLI rather than its README prose:
  - `mdguard check` → `mdguard . --json` (no `check` subcommand; takes paths)
  - `graft scan --json` → `graft . --check` (no `scan` subcommand, no `--json`)
  - `config-drift diff --fail-on-drift` → now passes the required
    `--configs-root` and `--environments`
  - `policy-runner run` → removed; `--task` and `--policy` are required, so it
    cannot have a zero-config default
  - `dep-health-scanner scan --json` → removed from the suite entirely; it
    requires `typer`, `rich` and `httpx`, breaking the zero-dependency
    invariant. Its console script is also `depscan`, not
    `dep-health-scanner`, so the original default could never have run.
- PyPI distribution names verified against the live index: `graft` publishes as
  `graft-inventory` (both `graft` and `graft-cli` are taken by other projects);
  `mdguard` and `policy-runner` keep their bare names.

### Added
- `bb doctor` shows `pip install <package>` for missing tools; the JSON output
  gains a `package` field.

### Changed
- Test suite: 103 → 110 tests, coverage held at 99%.

## [0.1.0] - 2026-08-20

### Added
- Initial release of `bb`, the BillyBox Toolbelt
- `bb doctor` — check which BillyBox tools are installed, with versions;
  `--strict` exits non-zero when any tool is missing
- `bb run <tool> [args...]` — passthrough to any installed tool, forwarding
  the tool's exit code
- `bb preflight` — run the configured quality gate with `--only`,
  `--fail-fast`, `--timeout`, `--verbose`, `--json` and `--no-color`
- `bb serve` — start `mockroute` using the project's route config
- `bb release` — produce release notes via `commitlog`
- `bb init` — scaffold `bb.json`, `.ctxignore`, `policy.json`, `routes.json`
  and `commitlog.json`; `--force` overwrites
- Config discovery: `bb.json`, falling back to `.billybox.json`
- Terminal dashboard and JSON output for both `preflight` and `doctor`
- Exit codes: 0 pass, 1 failure, 2 configuration error

### Security
- All subprocesses run with explicit `shell=False` and `check=False`
- Command lines tokenised with `shlex.split`, never interpolated into a shell
- Executables validated against `^[A-Za-z0-9._\-/\\:]+$`; shell metacharacters
  are rejected and reported as skipped
- `--repo` resolved with `Path.resolve(strict=True)` and required to be a
  directory
- Per-step timeouts (default 120s)

### Quality
- Zero runtime dependencies (Python 3.9+ stdlib only)
- 103 tests, 99% coverage
- CI: pytest matrix (3.9–3.12), ruff check + format, mypy, build + entry-point
  verification
- Pre-commit hooks (ruff, ruff-format, file checks)

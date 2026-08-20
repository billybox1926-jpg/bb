# Changelog

All notable changes to this project will be documented in this file.

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

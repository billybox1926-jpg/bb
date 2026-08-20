# Contributing to bb

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/billybox1926-jpg/bb.git
cd bb
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest pytest-cov ruff mypy pre-commit
pre-commit install
```

## Running Tests

```bash
pytest tests/ -v
```

Coverage must stay at or above 85%.

## Before Pushing

```bash
ruff check bb.py tests/test_bb.py
ruff format --check bb.py tests/test_bb.py
mypy bb.py --ignore-missing-imports
pytest tests/ -v
```

## Code Style

- Zero runtime dependencies — standard library only
- Python 3.9+ compatible
- Follow PEP 8; line length 88
- Type hints on public functions
- Keep functions focused and small

## Security

`bb` executes subprocesses. Any change touching `subprocess`, command parsing,
or path handling must:

- keep `shell=False`
- keep `check=False` explicit
- validate the executable via `validate_command`
- ship a test covering the new path

## Commit Messages

Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`.

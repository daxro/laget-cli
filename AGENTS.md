# Project Instructions

Read `README.md` in full before changing the CLI contract or taking actions that affect users.

## Purpose

`laget-cli` is an unofficial, agent-independent CLI for laget.se. Keep it small, predictable, secure, and usable by people, scripts, and any software agent.

## Architecture

- `laget_cli/cli.py`: argparse interface, validation, command handlers, JSON output
- `laget_cli/errors.py`: structured errors and exit codes
- `laget_cli/session.py`: authentication and persisted session cookies
- `laget_cli/paths.py`: platform-standard paths and atomic writes
- `laget_cli/api/`: fetching and normalization by resource
- `tests/`: behavior and contract tests

## Development

```bash
uv sync --locked --all-groups
uv run pytest
uv build
uv run laget --help
```

Before writing calls to an external API, run `chub search <api-name>` and fetch the relevant documentation with `chub get <id>`.

## Invariants

- Preserve argparse, existing JSON shapes, and the exit-code taxonomy unless a requested change requires otherwise.
- Emit data JSON on stdout. Emit structured errors and optional progress on stderr.
- Never expose credentials, cookies, or session data in output, errors, logs, tests, or documentation.
- Authenticate new credentials in a fresh session before replacing working credentials.
- Write config, session, and state atomically with `0600` permissions.
- Keep calendar reads bounded and stop fetching when a limit is satisfied.
- Keep collection team filters multi-match. Require an exact team slug for RSVP.
- Add focused tests for behavior changes and run the full suite.
- Keep portable guidance here. Do not add vendor-specific agent instructions or skills.

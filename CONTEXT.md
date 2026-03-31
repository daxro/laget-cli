# Context

Laget CLI fetches team data from laget.se (Swedish sports team platform) via email/password authentication.

## Architecture

```
laget_cli/
  cli.py         - Argparse-based CLI entry point, command handlers, output formatting
  errors.py      - Structured JSON error output, exit codes
  session.py     - Login flow: POST credentials, CSRF token, cookie persistence
  paths.py       - XDG-compliant config/state paths via platformdirs
  api/
    __init__.py  - Re-exports from submodules
    calendar.py  - Calendar event listing and date-range fetching
    news.py      - News article fetching with comments
    notifications.py - Activity feed parsing, team name resolution
    normalize.py - HTML-to-data normalization helpers
    teams.py     - Team listing, child-team mapping, club filtering
```

## Data flow

1. User runs a command (e.g., `laget notifications`)
2. `cli.py` loads config from `~/.config/laget/config.env`
3. `session.py` authenticates (reuses cached session cookies if valid)
4. `api/` modules fetch HTML pages from laget.se, parse them into structured data
5. JSON output goes to stdout, progress/errors to stderr

## Authentication

laget.se uses a standard form login: GET login page for CSRF token, POST credentials, follow redirects, verify with a lightweight endpoint. Session cookies are persisted to disk and reused until they expire.

## Key conventions

- All data output is JSON on stdout
- All errors are structured JSON on stderr: `{"error": "code", "message": "text"}`
- Exit codes: 0=success, 1=error, 2=usage, 3=auth, 4=not_found, 5=network
- Progress messages go to stderr, suppressed with -q/--quiet
- Config: `~/.config/laget/config.env` (EMAIL, PASSWORD, optional CLUB filter)
- Session cache: `~/.local/state/laget/session.json`
- State cache: `~/.local/state/laget/state.json` (child-team mapping, synced on auth)

# laget-cli

An unofficial CLI for [laget.se](https://www.laget.se).

For humans - stop checking the laget.se web UI. laget-cli gives you `--help` on every command, structured JSON output, and date filtering.

For AI agents - every response is JSON to stdout, errors are JSON to stderr with distinct exit codes. Pass `-q` to suppress progress messages.

## Prerequisites

- Python 3.10+
- A laget.se account (parent or member)

## Install

```bash
uv tool install git+https://github.com/daxro/laget-cli.git
```

**Development install:**

```bash
git clone https://github.com/daxro/laget-cli.git
cd laget-cli
uv sync
uv run laget --version
```

## Setup

```bash
laget setup
```

Prompts for email and password, authenticates, and optionally sets a club filter to limit which teams appear.

Non-interactive (pass credentials via env vars):

```bash
EMAIL=you@example.com PASSWORD=secret laget setup --no-input
```

For agents: do NOT run `laget setup` directly or tell the user to run it - it requires interactive input you cannot provide. Instead:

1. Ask the user: "What is your laget.se email and password?"
2. Run: `EMAIL=<email> PASSWORD=<password> laget setup --no-input -q`

This applies whenever a command fails with exit code 2 and `"not_configured"` error. `--no-input` only affects `setup` - other commands never prompt for input.

## Usage

```bash
laget status                                  # human-readable status
laget status --json                           # machine-readable status
laget calendar                                # upcoming events (next 30 days)
laget calendar --since 2026-04-01 --until 2026-04-30
laget calendar --team P2019 --limit 5         # filter by team, cap results
laget event --team P2019 12345                # event detail with RSVP
laget notifications                           # activity feed (last 30 days)
laget notifications --since all               # all notifications, no date limit
laget notifications --team Knatte --limit 10  # filter by team, cap results
laget news --team P2019 67890                 # full article with comments
laget reset                                   # remove config, session, and state files
```

All data commands output JSON to stdout. Progress messages go to stderr (suppress with `-q`). Use `--fields date,type` to filter output fields, `--no-input` to prevent interactive prompts, `--debug` to log HTTP traffic.

For agents: pipe through `jq` for field extraction, e.g. `laget notifications -q | jq '.[].type'`. Use `laget status --json -q | jq '.configured'` to verify setup.

## Flags

| Flag | Description |
|------|-------------|
| -q / --quiet | Suppress progress messages on stderr |
| --no-input | Skip interactive prompts (setup only) |
| --fields x,y | Filter JSON output to specific fields (e.g. --fields date,type,title) |
| --debug | Log HTTP requests to stderr |
| --since DATE | Start date (YYYY-MM-DD or 'all'). Notifications default: 30 days ago. Calendar default: today |
| --until DATE | End date (YYYY-MM-DD or 'all'). Notifications default: no limit. Calendar default: 30 days from today |
| --team SLUG | Filter by team slug (case-insensitive substring match). For news/event, ambiguous matches use the first result |
| --limit N | Maximum number of results to return |
| --version | Show version and exit |
| --json | Output as JSON (status only) |

## Configuration

Config and state are stored in platform-standard directories (via [platformdirs](https://pypi.org/project/platformdirs/)):

| File | Linux | macOS |
|------|-------|-------|
| Config | `~/.config/laget/config.env` | `~/Library/Application Support/laget/config.env` |
| Session | `~/.local/state/laget/session.json` | `~/Library/Application Support/laget/session.json` |
| State | `~/.local/state/laget/state.json` | `~/Library/Application Support/laget/state.json` |

Run `laget status --json` to see the actual paths on your system.

Optional config variables in `config.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUB` | (none) | Case-insensitive substring filter for team club names |
| `DEFAULT_SINCE_DAYS` | `30` | Rolling window for notifications `--since` default (calendar uses today as default) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid input / not configured |
| 3 | Authentication error |
| 4 | Resource not found |
| 5 | Network error |

Errors are emitted as JSON to stderr:

```json
{"error": "auth_failed", "message": "Login failed. Check your credentials."}
```

For agents: sessions expire and the CLI re-authenticates automatically on the next command. If a command fails with exit code 3, credentials may be wrong - tell the user to re-run `laget setup`.

## Output

Status (`laget status --json`):

```json
{
  "configured": true,
  "email": "use****@example.com",
  "club_filter": "Example FC",
  "session": "valid",
  "teams": [
    {"name": "P2021", "club": "Example FC", "team_slug": "ExampleFC-P2021"}
  ],
  "children": [
    {"name": "Alice Testsson", "id": "1234567"}
  ]
}
```

Calendar:

```json
[
  {
    "team": "P2021",
    "team_slug": "ExampleFC-P2021",
    "events": [
      {
        "id": "12345",
        "type": "training",
        "title": "Traning",
        "cancelled": false,
        "date": "2026-04-02T17:00:00",
        "start_time": "17:00",
        "end_time": "18:00",
        "location": null,
        "assembly_time": null,
        "location_url": null,
        "notes": null,
        "rsvp": null
      }
    ]
  }
]
```

Notifications:

```json
[
  {
    "date": "2026-03-29T18:45:00",
    "type": "guestbook",
    "author": "Bob Testsson",
    "title": "Skrev i gastboken",
    "team": "P2021",
    "team_slug": "ExampleFC-P2021",
    "url": "/ExampleFC-P2021/Guestbook"
  }
]
```

Notification types: `news`, `news_comment`, `guestbook`, `rsvp`, `unknown`.

## Uninstall

```bash
laget reset -q                             # remove config, session, and state
uv tool uninstall laget-cli                # remove the binary
```

## Testing

```bash
uv run pytest
```

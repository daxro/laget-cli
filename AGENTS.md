# Agent Guide

How to use laget-cli from automated scripts and AI agents.

## Setup (non-interactive)

```bash
EMAIL=user@example.com PASSWORD=secret laget setup --no-input -q
```

Credentials are saved to `~/.config/laget/config.env`. The session is cached for reuse.

## Commands

```bash
laget status -q                                 # Human-readable status to stderr
laget status --json -q                          # Machine-readable status check
laget notifications -q                          # JSON array of recent activity (last 30 days)
laget notifications -q --team tigers            # Filter by team (substring match)
laget notifications -q --since 2026-01-01       # Activity since a date
laget notifications -q --limit 10               # Cap results
laget calendar -q                               # Upcoming events (next 30 days)
laget calendar -q --since 2026-01-01 --limit 5  # Events since a date, limited per team
laget news --team tigers 12345 -q               # News article with comments
laget event --team tigers 67890 -q              # Event detail with RSVPs
```

## Flags

| Flag | Description |
|------|-------------|
| -q / --quiet | Suppress progress messages on stderr |
| --no-input | Never prompt for input (fail if input would be needed) |
| --fields x,y | Filter output to specific fields |
| --debug | Log HTTP requests to stderr |
| --json | (status only) Output as JSON |

## Error handling

Errors are JSON on stderr with distinct exit codes:

```json
{"error": "error_code", "message": "Human-readable message"}
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Success |
| 2 | Invalid input / usage error |
| 3 | Authentication error |
| 4 | Resource not found |
| 5 | Network error |

## Parsing output

All data commands output valid JSON to stdout. Use jq or json.loads():

```bash
laget notifications -q | jq '.[0].type'
laget status --json -q | jq '.session'
laget calendar -q --fields date,title | jq '.[].events'
```

## Session management

Sessions are cached at `~/.local/state/laget/session.json`. They expire server-side.
If you get exit code 3, re-run `laget setup --no-input -q` to re-authenticate.
The `status --json` command checks session validity without side effects.

## Team resolution

The `--team` flag accepts a substring match (case-insensitive) against team slugs.
For commands that require `--team` (news, event), an ambiguous match uses the first result with a warning on stderr.

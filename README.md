# laget-cli

An unofficial command-line interface for [laget.se](https://www.laget.se). It uses undocumented web endpoints and may break when laget.se changes.

`laget-cli` is designed for people, scripts, and any software agent that can run a CLI and consume JSON.

## Install

Install the latest source:

```bash
uv tool install git+https://github.com/daxro/laget-cli.git
```

Update an existing install:

```bash
uv tool upgrade laget-cli
```

Pin a commit for reproducible automation:

```bash
uv tool install git+https://github.com/daxro/laget-cli.git@<commit-sha>
```

Requires Python 3.10 or later and a laget.se account.

## Secure Setup

A person should run setup privately:

```bash
laget setup
```

Setup authenticates before replacing any existing credentials or session. Credentials are stored locally with `0600` permissions.

Agents must never ask users to paste credentials, receive credentials, or embed credentials in commands, logs, prompts, or files. If a command returns `not_configured`, stop and ask the user to complete `laget setup` privately.

For trusted user-managed automation, a secret manager or execution environment can provide namespaced variables:

```bash
LAGET_EMAIL=... LAGET_PASSWORD=... laget setup --no-input -q
```

The legacy `EMAIL` and `PASSWORD` environment variables remain temporarily supported and emit a deprecation warning.

## Agent Contract

- Data commands emit JSON to stdout.
- Errors emit one JSON object to stderr and use the exit codes below.
- Progress goes to stderr. Use `-q` to suppress it.
- Prefer bounded reads: use date ranges, `--limit`, and `--fields`.
- `calendar` and `notifications` team filters may match multiple teams.
- `news` and `event` accept an exact slug or a unique substring. Ambiguous matches fail.
- `rsvp` requires an exact team slug and changes remote state.
- `reset` deletes local credentials, session, and state.
- `--debug` may expose sensitive HTTP details. Review debug output before sharing it.

## Commands

```bash
laget status --json -q
laget notifications --since 2026-06-01 --limit 10 -q
laget notifications --team P2019 --fields date,type,title -q
laget calendar --until 2026-07-05 --limit 5 -q
laget calendar --team P2019 --fields id,date,title -q
laget news --team ExampleFC-P2019 67890 -q
laget event --team ExampleFC-P2019 12345 -q
laget rsvp --team ExampleFC-P2019 12345 yes -q
laget reset -q
```

Dates must be real ISO dates in `YYYY-MM-DD` format. Calendar ranges are limited to 24 months. For calendar, `--since all` means one year ago and `--until all` means one year ahead; using both gives the bounded two-year range.

`--fields` rejects unknown or empty fields. It filters notification records, event/detail/status/reset objects, and calendar event objects while preserving each calendar team envelope.

Compact success output:

```json
[{"team":"P2019","team_slug":"ExampleFC-P2019","events":[{"id":"12345","date":"2026-06-12T17:00:00","title":"Training"}]}]
```

Error output:

```json
{"error":"ambiguous_team","message":"Multiple teams match 'P2019': ExampleFC-P2019, OtherFC-P2019. Use an exact team slug."}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Unexpected or general error |
| `2` | Invalid input or not configured |
| `3` | Authentication error |
| `4` | Resource not found |
| `5` | Network error |
| `130` | Interrupted |

## Local Files

Run `laget status --json` to see the actual config and session paths for the current platform. Config, session, and state files are written atomically with `0600` permissions.

## Uninstall

```bash
laget reset -q
uv tool uninstall laget-cli
```

## Development

```bash
git clone https://github.com/daxro/laget-cli.git
cd laget-cli
uv sync --locked --all-groups
uv run pytest
uv build
```

See [SECURITY.md](SECURITY.md) for private vulnerability reporting.

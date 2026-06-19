"""laget-cli - fetch data from laget.se."""

import argparse
import getpass
import json
import os
import re
import sys
from datetime import date, timedelta
from importlib.metadata import version as _pkg_version

import requests
from dotenv import dotenv_values

from laget_cli.errors import (
    AuthError,
    ParseError,
    emit_error,
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
)
from laget_cli.api import fetch_article, fetch_calendar_range, fetch_event_detail, fetch_notifications, fetch_teams, fetch_children, filter_teams_by_club, submit_rsvp, sync_child_team_mapping
from laget_cli.api.notifications import resolve_team_names
from laget_cli.paths import CONFIG_FILE, SESSION_FILE, STATE_FILE, atomic_write_text
from laget_cli.session import login, save_session

try:
    import argcomplete
    _HAS_ARGCOMPLETE = True
except ImportError:
    _HAS_ARGCOMPLETE = False


_DEFAULT_SINCE_DAYS = 30
_MAX_CALENDAR_MONTHS = 24

_STATUS_FIELDS = {
    "configured", "email", "club_filter", "session", "teams", "children",
    "config_path", "session_path",
}
_NOTIFICATION_FIELDS = {"date", "type", "author", "title", "team", "team_slug", "url"}
_CALENDAR_EVENT_FIELDS = {
    "id", "type", "title", "cancelled", "date", "start_time", "end_time",
    "location", "assembly_time", "location_url", "notes", "rsvp",
}
_NEWS_FIELDS = {
    "id", "team", "team_slug", "title", "author", "date", "body",
    "view_count", "comments",
}
_EVENT_FIELDS = _CALENDAR_EVENT_FIELDS | {"team", "team_slug", "responses"}
_RESET_FIELDS = {"reset", "deleted", "failed"}
_legacy_credentials_warned = False


class _LagetParser(argparse.ArgumentParser):
    """ArgumentParser that emits JSON errors to stderr."""

    def error(self, message):
        error = {"error": "usage_error", "message": message}
        print(json.dumps(error), file=sys.stderr)
        self.exit(EXIT_USAGE)


def _load_config():
    """Read the private config without expanding credential-like values."""
    return dotenv_values(CONFIG_FILE, interpolate=False)


def _configure_debug():
    """Enable debug logging of HTTP requests to stderr."""
    import logging
    print(
        "Warning: --debug output may contain sensitive data. Review it before sharing.",
        file=sys.stderr,
    )
    logging.basicConfig(
        format="%(levelname)s %(name)s: %(message)s",
        level=logging.DEBUG,
        stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.DEBUG)


def _progress(message, quiet=False):
    """Print progress message to stderr unless quiet mode is enabled."""
    if not quiet:
        print(message, file=sys.stderr)


def _mask_email(email):
    """user@example.com -> use****@example.com"""
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 3:
        masked = local[0] + "****"
    else:
        masked = local[:3] + "****"
    return f"{masked}@{domain}"


def _warn_legacy_credentials(source, quiet=False):
    global _legacy_credentials_warned
    if not quiet and not _legacy_credentials_warned:
        print(
            f"Warning: EMAIL and PASSWORD in {source} are deprecated; "
            "use LAGET_EMAIL and LAGET_PASSWORD.",
            file=sys.stderr,
        )
        _legacy_credentials_warned = True


def _credentials_from_mapping(values, source, warn_legacy=False, quiet=False):
    """Return namespaced credentials, with a temporary legacy fallback."""
    email = values.get("LAGET_EMAIL")
    password = values.get("LAGET_PASSWORD")
    if email or password:
        return email, password

    email = values.get("EMAIL")
    password = values.get("PASSWORD")
    if (email or password) and warn_legacy:
        _warn_legacy_credentials(source, quiet=quiet)
    return email, password


def _get_session(quiet=False):
    """Authenticate and return a session without additional data fetching."""
    config = _load_config()
    email, password = _credentials_from_mapping(config, str(CONFIG_FILE))
    if not email or not password:
        emit_error("not_configured", "Credentials not set. Run: laget setup", exit_code=EXIT_USAGE)
    _progress("Authenticating...", quiet)
    return login(email, password, session_path=str(SESSION_FILE))


def _sync_state(session, config, teams=None, children=None, quiet=False):
    """Sync child-team mapping after successful auth."""
    try:
        if teams is None:
            teams = filter_teams_by_club(fetch_teams(session), config.get("CLUB"))
        if children is None:
            children = fetch_children(session)
        mapping = sync_child_team_mapping(session, teams, children)
        team_names = {t["team_slug"]: t["name"] for t in teams}
        state = {
            "child_teams": {
                cid: {"team_slug": slug, "team_name": team_names.get(slug, slug)}
                for cid, slug in mapping.items()
            }
        }
        atomic_write_text(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))
        return state
    except (OSError, KeyError, ParseError, requests.RequestException) as e:
        _progress(f"Warning: could not sync child-team mapping: {e}", quiet)
        return None


def _load_state():
    """Load cached state (child-team mapping). Returns empty dict on failure."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _get_status(session=None, config=None, teams=None, children=None):
    """Build status dict from config and session state."""
    config = _load_config() if config is None else config
    email, password = _credentials_from_mapping(config, str(CONFIG_FILE))
    club_filter = config.get("CLUB")

    status = {
        "configured": bool(email and password),
        "email": _mask_email(email) if email else None,
        "club_filter": club_filter,
        "session": None,
        "teams": [],
        "children": [],
        "config_path": str(CONFIG_FILE),
        "session_path": str(SESSION_FILE),
    }

    if status["configured"]:
        if session is None:
            session = login(email, password, session_path=str(SESSION_FILE))
        status["session"] = "valid"
        teams_available = teams is not None
        children_available = children is not None
        if not teams_available:
            try:
                teams = fetch_teams(session)
                teams = filter_teams_by_club(teams, club_filter)
                teams_available = True
            except (requests.RequestException, ParseError) as e:
                print(f"Warning: could not fetch teams: {e}", file=sys.stderr)
                teams = []
        status["teams"] = teams
        if not children_available:
            try:
                children = fetch_children(session)
                children_available = True
            except (requests.RequestException, ParseError, KeyError) as e:
                print(f"Warning: could not fetch children: {e}", file=sys.stderr)
                children = []

        state = (
            _sync_state(session, config, teams=teams, children=children, quiet=True)
            if teams_available and children_available
            else None
        )
        state = state if state is not None else _load_state()
        child_teams = state.get("child_teams", {})
        for child in children:
            ct = child_teams.get(child["id"])
            child["team_slug"] = ct["team_slug"] if ct else None
            child["team_name"] = ct["team_name"] if ct else None
        status["children"] = children

    return status


def _print_status(status):
    """Print human-readable status to stdout."""
    if not status["configured"]:
        print("Not configured. Run: laget setup")
        return

    print(f"Email: {status['email']}")
    if status["club_filter"]:
        print(f"Club: {status['club_filter']}")
    print(f"Config: {status['config_path']}")
    print(f"Session: {status['session']}")
    if status["session"] == "expired":
        print("  Run any command to re-authenticate.")
    if status["teams"]:
        print("Teams:")
        for team in status["teams"]:
            print(f"  - {team['name']} ({team['club']})")
    if status["children"]:
        print("Children:")
        for child in status["children"]:
            team = child.get("team_name")
            if team:
                print(f"  - {child['name']} -> {team}")
            else:
                print(f"  - {child['name']}")


def _status(args):
    if getattr(args, "fields", None) and not getattr(args, "json_output", False):
        emit_error("invalid_input", "--fields requires status --json.", exit_code=EXIT_USAGE)
    _validate_fields(args, _STATUS_FIELDS, "status")
    status = _get_status()
    if getattr(args, "json_output", False):
        _output_json(status, args, _STATUS_FIELDS)
    else:
        _print_status(status)
    if not status["configured"]:
        sys.exit(EXIT_USAGE)


def _setup(args):
    _reject_fields(args, "setup")
    non_interactive = getattr(args, "no_input", False) or not sys.stdin.isatty()
    if not non_interactive:
        print_logo()
    existing_config = _load_config()
    existing_email, existing_password = _credentials_from_mapping(
        existing_config, str(CONFIG_FILE)
    )

    if non_interactive:
        email, password = _credentials_from_mapping(
            os.environ,
            "the environment",
            warn_legacy=True,
            quiet=args.quiet,
        )
        if not email or not password:
            emit_error(
                "setup_required",
                "LAGET_EMAIL and LAGET_PASSWORD are required in non-interactive mode.",
                exit_code=EXIT_USAGE,
        )
        _validate_credentials(email, password)
        session = login(email, password, session_path=None)
        same_account = bool(
            existing_email and email.casefold() == existing_email.casefold()
        )
        club = (
            existing_config.get("CLUB")
            if same_account
            else None
        )
        _persist_setup(email, password, club, session, reset_state=not same_account)
        _progress("Authenticated.", args.quiet)
        config = _config_values(email, password, club)
        _print_status(_get_status(session=session, config=config))
        return

    if existing_email:
        print(f"Already configured ({_mask_email(existing_email)})", file=sys.stderr)
        answer = input("Overwrite? [y/N] ").strip().lower()
        if answer != "y":
            login(existing_email, existing_password, session_path=str(SESSION_FILE))
            _progress("Authenticated.", args.quiet)
            return

    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    _validate_credentials(email, password)

    session = login(email, password, session_path=None)
    same_account = bool(existing_email and email.casefold() == existing_email.casefold())
    club = None
    teams = None

    try:
        teams = fetch_teams(session)
        clubs = sorted(set(t["club"] for t in teams))
        if len(clubs) > 1:
            print("\nYour teams span multiple clubs:", file=sys.stderr)
            for i, club_name in enumerate(clubs, 1):
                club_teams = [t["name"] for t in teams if t["club"] == club_name]
                print(f"  {i}. {club_name} ({', '.join(club_teams)})", file=sys.stderr)
            print(f"  0. Show all (no filter)", file=sys.stderr)
            choice = input("\nFilter by club [0]: ").strip()
            if choice and choice != "0" and choice.isdigit() and 1 <= int(choice) <= len(clubs):
                club = clubs[int(choice) - 1]
            elif choice == "0":
                club = None
    except (ParseError, requests.RequestException) as e:
        print(f"Warning: could not fetch teams for club selection: {e}", file=sys.stderr)

    _persist_setup(email, password, club, session, reset_state=not same_account)
    _progress(f"Saved credentials to {CONFIG_FILE}.", args.quiet)
    _progress("Setup complete. Authenticated successfully.", args.quiet)
    config = _config_values(email, password, club)
    if teams is not None:
        teams = filter_teams_by_club(teams, club)
    _print_status(_get_status(session=session, config=config, teams=teams))


def _validate_credentials(email, password):
    if not email or not password:
        emit_error("invalid_input", "Email and password are required.", exit_code=EXIT_USAGE)
    if "\n" in email or "\r" in email or "\n" in password or "\r" in password:
        emit_error(
            "invalid_input",
            "Email and password must not contain newline characters.",
            exit_code=EXIT_USAGE,
        )


def _dotenv_quote(value):
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def _config_values(email, password, club=None, default_since_days=None):
    config = {"LAGET_EMAIL": email, "LAGET_PASSWORD": password}
    if club:
        config["CLUB"] = club
    if default_since_days:
        config["DEFAULT_SINCE_DAYS"] = default_since_days
    return config


def _write_env(email, password, club=None):
    """Write credentials to config file."""
    existing = _load_config()
    lines = [
        f"LAGET_EMAIL={_dotenv_quote(email)}\n",
        f"LAGET_PASSWORD={_dotenv_quote(password)}\n",
    ]
    if club:
        lines.append(f"CLUB={_dotenv_quote(club)}\n")
    if existing.get("DEFAULT_SINCE_DAYS"):
        lines.append(f"DEFAULT_SINCE_DAYS={existing['DEFAULT_SINCE_DAYS']}\n")
    atomic_write_text(CONFIG_FILE, "".join(lines))


def _persist_setup(email, password, club, session, reset_state=False):
    """Persist setup files transactionally, invalidating state on account switch."""
    previous_config = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else None
    previous_session = SESSION_FILE.read_text(encoding="utf-8") if SESSION_FILE.exists() else None
    previous_state = (
        STATE_FILE.read_text(encoding="utf-8")
        if reset_state and STATE_FILE.exists()
        else None
    )
    try:
        _write_env(email, password, club)
        save_session(session, SESSION_FILE)
        if reset_state:
            atomic_write_text(STATE_FILE, json.dumps({"child_teams": {}}, indent=2))
    except Exception:
        _restore_file(CONFIG_FILE, previous_config)
        _restore_file(SESSION_FILE, previous_session)
        if reset_state:
            _restore_file(STATE_FILE, previous_state)
        raise


def _restore_file(path, previous_text):
    if previous_text is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    else:
        atomic_write_text(path, previous_text)


def _validate_date_flag(value, flag_name):
    """Validate a date flag is a real YYYY-MM-DD date or 'all'."""
    if value is None:
        return None
    if value.lower() == "all":
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        emit_error("invalid_input", f"{flag_name} must be YYYY-MM-DD or 'all'.", exit_code=EXIT_USAGE)
    try:
        date.fromisoformat(value)
    except ValueError:
        emit_error("invalid_input", f"{flag_name} must be a real calendar date.", exit_code=EXIT_USAGE)
    return value


def _validate_date_range(since, until):
    if since is not None and until is not None and since > until:
        emit_error(
            "invalid_input",
            "--since must be on or before --until.",
            exit_code=EXIT_USAGE,
        )


def _resolve_since(cli_value, config):
    """Resolve effective --since date. Priority: explicit flag > DEFAULT_SINCE_DAYS > 30 days."""
    if cli_value is not None:
        return _validate_date_flag(cli_value, "--since")
    days_str = config.get("DEFAULT_SINCE_DAYS")
    if days_str is not None:
        if not days_str.lstrip("-").isdigit() or int(days_str) <= 0:
            emit_error(
                "invalid_input",
                f"DEFAULT_SINCE_DAYS must be a positive integer, got '{days_str}'.",
                exit_code=EXIT_USAGE,
            )
        days = int(days_str)
    else:
        days = _DEFAULT_SINCE_DAYS
    return (date.today() - timedelta(days=days)).isoformat()


def _resolve_until(cli_value):
    """Resolve effective --until date. Only explicit flag supported for now."""
    if cli_value is not None:
        return _validate_date_flag(cli_value, "--until")
    return None


def _positive_int(value):
    try:
        parsed = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("must be a positive integer") from e
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _numeric_id(value):
    if not re.fullmatch(r"\d+", value):
        raise argparse.ArgumentTypeError("must contain digits only")
    return value


def _validate_fields(args, allowed_fields, command):
    """Validate and cache a command's selected output fields."""
    fields_str = getattr(args, "fields", None)
    if not isinstance(fields_str, str):
        return None
    fields = {field.strip() for field in fields_str.split(",") if field.strip()}
    if not fields:
        emit_error("invalid_input", "--fields must not be empty.", exit_code=EXIT_USAGE)
    unknown = sorted(fields - allowed_fields)
    if unknown:
        emit_error(
            "invalid_input",
            f"Unsupported --fields for {command}: {', '.join(unknown)}.",
            exit_code=EXIT_USAGE,
        )
    args.selected_fields = fields
    return fields


def _reject_fields(args, command):
    if isinstance(getattr(args, "fields", None), str):
        emit_error(
            "invalid_input",
            f"--fields is not supported by {command}.",
            exit_code=EXIT_USAGE,
        )


def _filter_fields(data, fields, nested_list_key=None):
    """Filter top-level dicts or records nested under an envelope key."""
    if fields is None:
        return data
    if nested_list_key is not None:
        return [
            {
                **item,
                nested_list_key: [
                    {key: value for key, value in record.items() if key in fields}
                    for record in item[nested_list_key]
                ],
            }
            for item in data
        ]
    if isinstance(data, list):
        return [{key: value for key, value in item.items() if key in fields} for item in data]
    if isinstance(data, dict):
        return {key: value for key, value in data.items() if key in fields}
    return data


def _output_json(data, args, allowed_fields, nested_list_key=None):
    """Print data as JSON to stdout, applying --fields filter if set."""
    fields = getattr(args, "selected_fields", None)
    if not isinstance(fields, set):
        fields = None
    if fields is None and isinstance(getattr(args, "fields", None), str):
        fields = _validate_fields(args, allowed_fields, args.command)
    data = _filter_fields(data, fields, nested_list_key=nested_list_key)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _shift_year(value, years):
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _month_start_after(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _calendar_range(raw_since, raw_until, today):
    """Resolve bounded calendar dates, including bounded 'all' aliases."""
    since_all = raw_since is not None and raw_since.lower() == "all"
    until_all = raw_until is not None and raw_until.lower() == "all"
    since_date = (
        today
        if raw_since is None
        else _shift_year(today, -1)
        if since_all
        else date.fromisoformat(_validate_date_flag(raw_since, "--since"))
    )
    until_date = (
        today + timedelta(days=30)
        if raw_until is None
        else _shift_year(today, 1)
        if until_all
        else date.fromisoformat(_validate_date_flag(raw_until, "--until"))
    )
    if since_all and until_all:
        until_date = _month_start_after(since_date, _MAX_CALENDAR_MONTHS) - timedelta(days=1)
    since = since_date.isoformat()
    until = until_date.isoformat()
    _validate_date_range(since, until)
    month_count = (
        (date.fromisoformat(until).year - date.fromisoformat(since).year) * 12
        + date.fromisoformat(until).month
        - date.fromisoformat(since).month
        + 1
    )
    if month_count > _MAX_CALENDAR_MONTHS:
        emit_error(
            "invalid_input",
            f"Calendar date range may span at most {_MAX_CALENDAR_MONTHS} months.",
            exit_code=EXIT_USAGE,
        )
    return since, until


def _filter_items_since(items, since, date_key="date"):
    """Filter items where item[date_key] >= since. None = no filter."""
    if since is None:
        return items
    return [item for item in items if item.get(date_key) and item[date_key] >= since]


def _filter_items_until(items, until, date_key="date"):
    """Filter items where item[date_key][:10] <= until. None = no filter."""
    if until is None:
        return items
    return [item for item in items if item.get(date_key) and item[date_key][:10] <= until]


def _filter_by_team(items, team_filter):
    """Filter items by team_slug substring match (case-insensitive). None = no filter."""
    if team_filter is None:
        return items
    team_filter_lower = team_filter.lower()
    return [item for item in items if team_filter_lower in item["team_slug"].lower()]


def _notifications(args):
    _validate_fields(args, _NOTIFICATION_FIELDS, "notifications")
    config = _load_config()
    since = _resolve_since(getattr(args, "since", None), config)
    until = _resolve_until(getattr(args, "until", None))
    _validate_date_range(since, until)
    team_filter = getattr(args, "team", None)

    session = _get_session(quiet=args.quiet)
    _progress("Fetching teams...", args.quiet)
    all_teams = fetch_teams(session)

    _progress("Fetching notifications...", args.quiet)
    notifications = fetch_notifications(session)
    resolve_team_names(notifications, all_teams)

    # Filter to club teams after resolving names (so all teams get names)
    club_filter = config.get("CLUB")
    if club_filter:
        club_slugs = {t["team_slug"] for t in filter_teams_by_club(all_teams, club_filter)}
        notifications = [n for n in notifications if n.get("team_slug") in club_slugs]

    notifications = _filter_by_team(notifications, team_filter)
    notifications = _filter_items_since(notifications, since)
    notifications = _filter_items_until(notifications, until)

    # Sort by date descending (newest first); items with no date go last
    notifications.sort(key=lambda n: n["date"] or "", reverse=True)

    limit = getattr(args, "limit", None)
    if limit is not None:
        notifications = notifications[:limit]

    _output_json(notifications, args, _NOTIFICATION_FIELDS)


def _news(args):
    _validate_fields(args, _NEWS_FIELDS, "news")
    session = _get_session(args.quiet)
    config = _load_config()
    club_filter = config.get("CLUB")

    teams = fetch_teams(session)
    teams = filter_teams_by_club(teams, club_filter)
    team_slug, team_name = _resolve_team_slug(args.team, teams)

    _progress(f"Fetching article {args.id}...", args.quiet)
    article = fetch_article(session, team_slug, args.id)
    article["team"] = team_name
    article["team_slug"] = team_slug

    _output_json(article, args, _NEWS_FIELDS)


def _resolve_team_slug(args_team, teams, exact=False):
    """Resolve a team arg (exact slug or substring) to (team_slug, team_name).

    Exits with an error if no match or ambiguous match.
    """
    team_slugs = {t["team_slug"]: t["name"] for t in teams}
    if args_team in team_slugs:
        return args_team, team_slugs[args_team]
    if exact:
        emit_error(
            "team_not_found",
            f"No team with exact slug '{args_team}'.",
            exit_code=EXIT_NOT_FOUND,
        )
    matches = [(slug, name) for slug, name in team_slugs.items() if args_team.lower() in slug.lower()]
    if not matches:
        emit_error("team_not_found", f"No team matching '{args_team}'.", exit_code=EXIT_NOT_FOUND)
    if len(matches) > 1:
        slugs = ", ".join(slug for slug, _ in matches)
        emit_error(
            "ambiguous_team",
            f"Multiple teams match '{args_team}': {slugs}. Use an exact team slug.",
            exit_code=EXIT_USAGE,
        )
    return matches[0]


def _calendar(args):
    _validate_fields(args, _CALENDAR_EVENT_FIELDS, "calendar")
    config = _load_config()
    team_filter = getattr(args, "team", None)
    limit = getattr(args, "limit", None)
    today = date.today()
    raw_since = getattr(args, "since", None)
    raw_until = getattr(args, "until", None)
    since, until = _calendar_range(raw_since, raw_until, today)

    session = _get_session(quiet=args.quiet)
    _progress("Fetching teams...", args.quiet)
    teams = fetch_teams(session)
    teams = filter_teams_by_club(teams, config.get("CLUB"))

    if team_filter:
        teams = [t for t in teams if team_filter.lower() in t["team_slug"].lower()]
        if not teams:
            emit_error("team_not_found", f"No team matching '{team_filter}'.", exit_code=EXIT_NOT_FOUND)

    output = []
    for team in teams:
        _progress(f"Fetching calendar for {team['team_slug']}...", args.quiet)
        events = fetch_calendar_range(session, team["team_slug"], since, until, limit=limit)
        output.append({
            "team": team["name"],
            "team_slug": team["team_slug"],
            "events": events,
        })

    _output_json(output, args, _CALENDAR_EVENT_FIELDS, nested_list_key="events")


def _event(args):
    _validate_fields(args, _EVENT_FIELDS, "event")
    session = _get_session(args.quiet)
    config = _load_config()
    club_filter = config.get("CLUB")

    teams = fetch_teams(session)
    teams = filter_teams_by_club(teams, club_filter)
    team_slug, team_name = _resolve_team_slug(args.team, teams)

    _progress(f"Fetching event {args.id}...", args.quiet)
    detail = fetch_event_detail(session, team_slug, args.id)
    detail["team"] = team_name

    _output_json(detail, args, _EVENT_FIELDS)


def _rsvp(args):
    _validate_fields(args, _EVENT_FIELDS, "rsvp")
    session = _get_session(args.quiet)
    config = _load_config()
    club_filter = config.get("CLUB")

    teams = fetch_teams(session)
    teams = filter_teams_by_club(teams, club_filter)
    team_slug, team_name = _resolve_team_slug(args.team, teams, exact=True)

    _progress(f"Fetching event {args.id}...", args.quiet)
    detail = fetch_event_detail(session, team_slug, args.id)
    rsvp = detail.get("rsvp")
    rsvp_url = rsvp.get("url") if rsvp else None
    if not rsvp_url:
        emit_error("rsvp_not_found", f"Event {args.id} has no RSVP link.", exit_code=EXIT_NOT_FOUND)

    _progress(f"Submitting RSVP for event {args.id}...", args.quiet)
    submit_rsvp(session, rsvp_url, args.response, comment=args.comment, event_id=args.id)

    _progress(f"Verifying RSVP for event {args.id}...", args.quiet)
    updated = fetch_event_detail(session, team_slug, args.id)
    updated["team"] = team_name
    updated_response = (updated.get("rsvp") or {}).get("my_response")
    if updated_response != args.response:
        emit_error(
            "rsvp_update_failed",
            f"RSVP update could not be verified: expected {args.response}, got {updated_response}.",
            exit_code=EXIT_ERROR,
        )

    _output_json(updated, args, _EVENT_FIELDS)


def _reset(args):
    """Remove all config, session, and state files."""
    _validate_fields(args, _RESET_FIELDS, "reset")
    deleted = []
    failed = []
    for path in [CONFIG_FILE, SESSION_FILE, STATE_FILE]:
        if path.exists():
            try:
                path.unlink()
                deleted.append(str(path))
            except OSError as e:
                failed.append(str(path))
                if not args.quiet:
                    print(f"Failed to delete {path}: {e}", file=sys.stderr)
    if not args.quiet and deleted:
        for p in deleted:
            print(f"Deleted {p}", file=sys.stderr)
    if not args.quiet and not deleted and not failed:
        print("Nothing to reset - no config or session files found.", file=sys.stderr)
    _output_json(
        {"reset": True, "deleted": deleted, "failed": failed},
        args,
        _RESET_FIELDS,
    )
    if failed:
        sys.exit(EXIT_ERROR)


_LOGO_LINES = [
    r" _                  _        ___ _    ___ ",
    r"| | __ _  __ _  ___| |_     / __| |  |_ _|",
    r"| |/ _` |/ _` |/ -_)  _|   | (__| |__ | | ",
    r"|_|\__,_|\__, |\___|_|      \___|____|___|",
    r"         |___/                            ",
]
_CYAN = "\033[36m"
_BOLD_WHITE = "\033[1m\033[97m"
_RESET = "\033[0m"
_SPLIT = 27


def _use_color():
    """Return True if stderr supports ANSI color."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if not hasattr(sys.stderr, "isatty") or not sys.stderr.isatty():
        return False
    return True


def print_logo():
    color = _use_color()
    for line in _LOGO_LINES:
        main_part = line[:_SPLIT]
        cli_part = line[_SPLIT:] if len(line) > _SPLIT else ""
        if color:
            print(f"{_CYAN}{main_part}{_RESET}{_BOLD_WHITE}{cli_part}{_RESET}", file=sys.stderr)
        else:
            print(f"{main_part}{cli_part}", file=sys.stderr)


def main():
    parser = _LagetParser(
        prog="laget",
        description="Fetch data from laget.se - teams, notifications, calendar, and more.",
        epilog="""examples:
  laget notifications                   Activity from last 30 days
  laget notifications --team tigers     Filter by team
  laget calendar --since 2026-01-01     Events since a date
  laget news --team tigers 12345        News article detail
  laget event --team tigers 67890       Event with RSVP details
  laget rsvp --team tigers 67890 yes    RSVP yes/no to an event""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_pkg_version('laget-cli')}")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress messages on stderr")
    parser.add_argument("--no-input", action="store_true", help="Never prompt for input (fail if input would be needed)")
    parser.add_argument("--debug", action="store_true", help="Log HTTP requests and responses to stderr")
    parser.add_argument("--fields", help="Comma-separated list of fields to include in JSON output (e.g. --fields date,type,title)")
    # Parent parser so global flags are accepted after the subcommand name too.
    # SUPPRESS on defaults prevents subparser defaults from clobbering root-parsed values.
    _global_flags = argparse.ArgumentParser(add_help=False)
    _global_flags.add_argument("-q", "--quiet", action="store_true",
                               default=argparse.SUPPRESS, help="Suppress progress messages on stderr")
    _global_flags.add_argument("--no-input", action="store_true",
                               default=argparse.SUPPRESS, help="Never prompt for input (fail if input would be needed)")
    _global_flags.add_argument("--debug", action="store_true",
                               default=argparse.SUPPRESS, help="Log HTTP requests and responses to stderr")
    _global_flags.add_argument("--fields",
                               default=argparse.SUPPRESS, help="Comma-separated list of fields to include in JSON output (e.g. --fields date,type,title)")

    subparsers = parser.add_subparsers(dest="command", title="commands", parser_class=_LagetParser)
    setup_parser = subparsers.add_parser(
        "setup", help="Configure credentials and club filter",
        parents=[_global_flags],
        epilog="""non-interactive mode:
  LAGET_EMAIL=you@example.com LAGET_PASSWORD=secret laget setup --no-input

  Reads credentials from LAGET_EMAIL and LAGET_PASSWORD environment variables.
  Prefer interactive setup when a person is available.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    status_parser = subparsers.add_parser("status", help="Show configuration, session, teams, and children",
                                          parents=[_global_flags])
    status_parser.add_argument("--json", dest="json_output", action="store_true", help="Output status as JSON to stdout")

    notif_parser = subparsers.add_parser(
        "notifications", help="Show recent activity feed across teams",
        parents=[_global_flags],
    )
    notif_parser.add_argument("--team", help="Filter by team slug (substring match)")
    notif_parser.add_argument("--since", help="Start date YYYY-MM-DD or 'all' (default: 30 days ago)")
    notif_parser.add_argument("--until", help="End date YYYY-MM-DD or 'all' (default: no limit)")
    notif_parser.add_argument("--limit", type=_positive_int, help="Maximum number of results to return")

    news_parser = subparsers.add_parser("news", help="Fetch a news article with comments",
                                        parents=[_global_flags])
    news_parser.add_argument("--team", required=True, help="Team slug (or substring)")
    news_parser.add_argument("id", type=_numeric_id, help="Article ID")

    cal_parser = subparsers.add_parser("calendar", help="List upcoming events across teams",
                                       parents=[_global_flags])
    cal_parser.add_argument("--team", help="Filter by team slug (substring match)")
    cal_parser.add_argument("--since", help="Start date YYYY-MM-DD or 'all' (bounded to 1 year ago; default: today)")
    cal_parser.add_argument("--until", help="End date YYYY-MM-DD or 'all' (bounded to 1 year ahead; default: 30 days from today)")
    cal_parser.add_argument("--limit", type=_positive_int, help="Maximum number of events per team to return")

    event_parser = subparsers.add_parser("event", help="Fetch event detail",
                                         parents=[_global_flags])
    event_parser.add_argument("--team", required=True, help="Team slug (or substring)")
    event_parser.add_argument("id", type=_numeric_id, help="Event ID")

    rsvp_parser = subparsers.add_parser("rsvp", help="RSVP yes/no to an event",
                                        parents=[_global_flags])
    rsvp_parser.add_argument("--team", required=True, help="Exact team slug")
    rsvp_parser.add_argument("id", type=_numeric_id, help="Event ID")
    rsvp_parser.add_argument("response", choices=["yes", "no"], help="RSVP response")
    rsvp_parser.add_argument("--comment", help="Optional RSVP comment when the event form supports comments")

    subparsers.add_parser("reset", parents=[_global_flags], help="Remove all config, session, and state files")

    if _HAS_ARGCOMPLETE:
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    if getattr(args, "debug", False):
        _configure_debug()

    if args.command is None:
        print_logo()
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "setup":
            _setup(args)
        elif args.command == "status":
            _status(args)
        elif args.command == "notifications":
            _notifications(args)
        elif args.command == "news":
            _news(args)
        elif args.command == "calendar":
            _calendar(args)
        elif args.command == "event":
            _event(args)
        elif args.command == "rsvp":
            _rsvp(args)
        elif args.command == "reset":
            _reset(args)
    except KeyboardInterrupt:
        emit_error("interrupted", "Interrupted by user.", exit_code=130)
    except AuthError as e:
        emit_error("auth_failed", str(e), exit_code=EXIT_AUTH)
    except ParseError as e:
        emit_error("parse_error", str(e))
    except requests.HTTPError as e:
        emit_error("http_error", f"HTTP error: {e}", exit_code=EXIT_NETWORK)
    except requests.Timeout:
        emit_error("request_timeout", "Request timed out.", exit_code=EXIT_NETWORK)
    except requests.ConnectionError:
        emit_error("connection_failed", "Connection failed. Check your network.", exit_code=EXIT_NETWORK)
    except requests.RequestException as e:
        emit_error("network_error", f"Network request failed: {e}", exit_code=EXIT_NETWORK)
    except Exception:
        if getattr(args, "debug", False):
            raise
        emit_error(
            "unexpected_error",
            "Unexpected error. Re-run with --debug and report it at "
            "https://github.com/daxro/laget-cli/issues.",
            exit_code=EXIT_ERROR,
        )

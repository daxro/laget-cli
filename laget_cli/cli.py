"""laget-cli - fetch data from laget.se."""

import argparse
import getpass
import json
import os
import re
import sys
from datetime import date, timedelta

import requests
from dotenv import dotenv_values

from laget_cli.errors import (
    AuthError,
    ParseError,
    emit_error,
    EXIT_AUTH,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
)
from laget_cli.api import fetch_article, fetch_calendar_range, fetch_event_detail, fetch_notifications, fetch_teams, fetch_children, filter_teams_by_club, sync_child_team_mapping
from laget_cli.api.notifications import resolve_team_names
from laget_cli.paths import CONFIG_DIR, CONFIG_FILE, SESSION_FILE, STATE_DIR, STATE_FILE
from laget_cli.session import login


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


def _get_session(quiet=False):
    """Authenticate and return a session. Syncs child-team mapping on auth. Exits if not configured."""
    config = dotenv_values(CONFIG_FILE)
    email = config.get("EMAIL")
    password = config.get("PASSWORD")
    if not email or not password:
        emit_error("not_configured", "Credentials not set. Run: laget setup", exit_code=EXIT_AUTH)
    _progress("Authenticating...", quiet)
    session = login(email, password, session_path=str(SESSION_FILE))
    _sync_state(session, config, quiet)
    return session


def _sync_state(session, config, quiet=False):
    """Sync child-team mapping after successful auth."""
    try:
        teams = fetch_teams(session)
        teams = filter_teams_by_club(teams, config.get("CLUB"))
        children = fetch_children(session)
        mapping = sync_child_team_mapping(session, teams, children)
        # Build team name lookup
        team_names = {t["team_slug"]: t["name"] for t in teams}
        state = {
            "child_teams": {
                cid: {"team_slug": slug, "team_name": team_names.get(slug, slug)}
                for cid, slug in mapping.items()
            }
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        _progress("Warning: could not sync child-team mapping.", quiet)


def _load_state():
    """Load cached state (child-team mapping). Returns empty dict on failure."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _get_status():
    """Build status dict from config and session state."""
    config = dotenv_values(CONFIG_FILE)
    email = config.get("EMAIL")
    club_filter = config.get("CLUB")

    status = {
        "configured": bool(email and config.get("PASSWORD")),
        "email": _mask_email(email) if email else None,
        "club_filter": club_filter,
        "session": None,
        "teams": [],
        "children": [],
    }

    if status["configured"]:
        try:
            session = _get_session(quiet=True)
            status["session"] = "valid"
            try:
                teams = fetch_teams(session)
                teams = filter_teams_by_club(teams, club_filter)
                status["teams"] = teams
            except Exception:
                pass
            try:
                children = fetch_children(session)
                state = _load_state()
                child_teams = state.get("child_teams", {})
                for child in children:
                    ct = child_teams.get(child["id"])
                    child["team_slug"] = ct["team_slug"] if ct else None
                    child["team_name"] = ct["team_name"] if ct else None
                status["children"] = children
            except Exception:
                pass
        except SystemExit:
            status["session"] = "expired"

    return status


def _print_status(status):
    """Print human-readable status to stderr."""
    if not status["configured"]:
        emit_error("not_configured", "Not configured. Run: laget setup", exit_code=EXIT_AUTH)

    print(f"Email: {status['email']}", file=sys.stderr)
    if status["club_filter"]:
        print(f"Club: {status['club_filter']}", file=sys.stderr)
    print(f"Session: {status['session']}", file=sys.stderr)
    if status["session"] == "expired":
        print("  Run any command to re-authenticate.", file=sys.stderr)
    if status["teams"]:
        print("Teams:", file=sys.stderr)
        for team in status["teams"]:
            print(f"  - {team['name']} ({team['club']})", file=sys.stderr)
    if status["children"]:
        print("Children:", file=sys.stderr)
        for child in status["children"]:
            team = child.get("team_name")
            if team:
                print(f"  - {child['name']} -> {team}", file=sys.stderr)
            else:
                print(f"  - {child['name']}", file=sys.stderr)


def _status(args):
    status = _get_status()
    if getattr(args, "json_output", False):
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    _print_status(status)


def _setup(args):
    print_logo()
    if not sys.stdin.isatty():
        email = os.environ.get("EMAIL")
        password = os.environ.get("PASSWORD")
        if not email or not password:
            emit_error(
                "setup_required",
                "EMAIL and PASSWORD env vars required in non-interactive mode.",
                exit_code=EXIT_USAGE,
            )
        _write_env(email, password)
        _progress("Saved credentials.", args.quiet)
        login(email, password, session_path=str(SESSION_FILE))
        _progress("Authenticated.", args.quiet)
        _print_status(_get_status())
        return

    existing_email = dotenv_values(CONFIG_FILE).get("EMAIL") if CONFIG_FILE.exists() else None
    if existing_email:
        print(f"Already configured ({_mask_email(existing_email)})", file=sys.stderr)
        answer = input("Overwrite? [y/N] ").strip().lower()
        if answer != "y":
            config = dotenv_values(CONFIG_FILE)
            login(config["EMAIL"], config["PASSWORD"], session_path=str(SESSION_FILE))
            _progress("Authenticated.", args.quiet)
            return

    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        emit_error("invalid_input", "Email and password are required.", exit_code=EXIT_USAGE)

    # Save credentials first (before auth attempt)
    _write_env(email, password)
    _progress(f"Saved to {CONFIG_FILE}", args.quiet)

    # Authenticate
    session = login(email, password, session_path=str(SESSION_FILE))
    print("Setup complete. Authenticated successfully.", file=sys.stderr)

    # Offer club filter selection
    try:
        teams = fetch_teams(session)
        clubs = sorted(set(t["club"] for t in teams))
        if len(clubs) > 1:
            print("\nYour teams span multiple clubs:", file=sys.stderr)
            for i, club in enumerate(clubs, 1):
                club_teams = [t["name"] for t in teams if t["club"] == club]
                print(f"  {i}. {club} ({', '.join(club_teams)})", file=sys.stderr)
            print(f"  0. Show all (no filter)", file=sys.stderr)
            choice = input("\nFilter by club [0]: ").strip()
            if choice and choice != "0" and choice.isdigit() and 1 <= int(choice) <= len(clubs):
                selected_club = clubs[int(choice) - 1]
                _write_env(email, password, club=selected_club)
                _progress(f"Club filter set to: {selected_club}", args.quiet)
    except Exception:
        print("Warning: could not fetch teams for club selection.", file=sys.stderr)

    # Show status after successful setup
    _print_status(_get_status())


def _write_env(email, password, club=None):
    """Write credentials to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"EMAIL={email}\n", f"PASSWORD={password}\n"]
    if club:
        lines.append(f"CLUB={club}\n")
    with open(CONFIG_FILE, "w") as f:
        f.writelines(lines)
    os.chmod(CONFIG_FILE, 0o600)


_DEFAULT_SINCE_DAYS = 30


def _validate_date_flag(value, flag_name):
    """Validate a date flag is YYYY-MM-DD or 'all'. Returns value, None, or exits."""
    if value is None:
        return None
    if value.lower() == "all":
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        emit_error("invalid_input", f"{flag_name} must be YYYY-MM-DD or 'all'.", exit_code=EXIT_USAGE)
    return value


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


def _filter_items_since(items, since, date_key="date"):
    """Filter items where item[date_key] >= since. None = no filter."""
    if since is None:
        return items
    return [item for item in items if item[date_key] >= since]


def _filter_items_until(items, until, date_key="date"):
    """Filter items where item[date_key][:10] <= until. None = no filter."""
    if until is None:
        return items
    return [item for item in items if item[date_key][:10] <= until]


def _filter_by_team(items, team_filter):
    """Filter items by team_slug substring match (case-insensitive). None = no filter."""
    if team_filter is None:
        return items
    team_filter_lower = team_filter.lower()
    return [item for item in items if team_filter_lower in item["team_slug"].lower()]


def _notifications(args):
    config = dotenv_values(CONFIG_FILE)
    since = _resolve_since(getattr(args, "since", None), config)
    until = _resolve_until(getattr(args, "until", None))
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

    print(json.dumps(notifications, ensure_ascii=False, indent=2))


def _news(args):
    session = _get_session(args.quiet)
    config = dotenv_values(CONFIG_FILE)
    club_filter = config.get("CLUB")

    teams = fetch_teams(session)
    teams = filter_teams_by_club(teams, club_filter)
    team_slug, team_name = _resolve_team_slug(args.team, teams)

    _progress(f"Fetching article {args.id}...", args.quiet)
    article = fetch_article(session, team_slug, args.id)
    article["team"] = team_name
    article["team_slug"] = team_slug

    print(json.dumps(article, ensure_ascii=False, indent=2))


def _resolve_team_slug(args_team, teams):
    """Resolve a team arg (exact slug or substring) to (team_slug, team_name).

    Exits with an error if no match or ambiguous match.
    """
    team_slugs = {t["team_slug"]: t["name"] for t in teams}
    if args_team in team_slugs:
        return args_team, team_slugs[args_team]
    matches = [(slug, name) for slug, name in team_slugs.items() if args_team.lower() in slug.lower()]
    if not matches:
        emit_error("team_not_found", f"No team matching '{args_team}'.", exit_code=EXIT_NOT_FOUND)
    if len(matches) > 1:
        print(f"Warning: multiple teams match '{args_team}', using first match.", file=sys.stderr)
    return matches[0]


def _calendar(args):
    config = dotenv_values(CONFIG_FILE)
    team_filter = getattr(args, "team", None)

    today = date.today()

    raw_since = getattr(args, "since", None)
    raw_until = getattr(args, "until", None)

    if raw_since is None:
        since = today.isoformat()
    elif raw_since.lower() == "all":
        since = None
    else:
        since = _validate_date_flag(raw_since, "--since")

    if raw_until is None:
        until = (today + timedelta(days=30)).isoformat()
    elif raw_until.lower() == "all":
        until = None
    else:
        until = _validate_date_flag(raw_until, "--until")

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
        events = fetch_calendar_range(session, team["team_slug"], since, until)
        events = _filter_items_since(events, since)
        events = _filter_items_until(events, until)
        if not events:
            continue
        output.append({
            "team": team["name"],
            "team_slug": team["team_slug"],
            "events": events,
        })

    print(json.dumps(output, ensure_ascii=False, indent=2))


def _event(args):
    session = _get_session(args.quiet)
    config = dotenv_values(CONFIG_FILE)
    club_filter = config.get("CLUB")

    teams = fetch_teams(session)
    teams = filter_teams_by_club(teams, club_filter)
    team_slug, team_name = _resolve_team_slug(args.team, teams)

    _progress(f"Fetching event {args.id}...", args.quiet)
    detail = fetch_event_detail(session, team_slug, args.id)
    detail["team"] = team_name

    print(json.dumps(detail, ensure_ascii=False, indent=2))


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


def print_logo():
    for line in _LOGO_LINES:
        main_part = line[:_SPLIT]
        cli_part = line[_SPLIT:] if len(line) > _SPLIT else ""
        print(f"{_CYAN}{main_part}{_RESET}{_BOLD_WHITE}{cli_part}{_RESET}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog="laget",
        description="Fetch data from laget.se - teams, notifications, calendar, and more.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress messages on stderr")
    subparsers = parser.add_subparsers(dest="command", title="commands")
    subparsers.add_parser("setup", help="Configure credentials and club filter")
    status_parser = subparsers.add_parser("status", help="Show configuration, session, teams, and children")
    status_parser.add_argument("--json", dest="json_output", action="store_true", help="Output status as JSON to stdout")

    notif_parser = subparsers.add_parser(
        "notifications", help="Show recent activity feed across teams"
    )
    notif_parser.add_argument("--team", help="Filter by team slug (substring match)")
    notif_parser.add_argument("--since", help="Start date YYYY-MM-DD (default: 30 days ago)")
    notif_parser.add_argument("--until", help="End date YYYY-MM-DD (default: no limit)")

    news_parser = subparsers.add_parser("news", help="Fetch a news article with comments")
    news_parser.add_argument("team", help="Team slug (or substring)")
    news_parser.add_argument("id", help="Article ID")

    cal_parser = subparsers.add_parser("calendar", help="List upcoming events across teams")
    cal_parser.add_argument("--team", help="Filter by team slug (substring match)")
    cal_parser.add_argument("--since", help="Start date YYYY-MM-DD (default: today)")
    cal_parser.add_argument("--until", help="End date YYYY-MM-DD (default: 30 days from today)")

    event_parser = subparsers.add_parser("event", help="Fetch event detail")
    event_parser.add_argument("team", help="Team slug (or substring)")
    event_parser.add_argument("id", help="Event ID")

    args = parser.parse_args()

    if args.command is None:
        print_logo()
        parser.print_help()
        sys.exit(1)

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

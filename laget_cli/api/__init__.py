"""laget.se API package."""

from laget_cli.api.calendar import fetch_calendar_range, fetch_event_detail
from laget_cli.api.news import fetch_article
from laget_cli.api.notifications import fetch_notifications
from laget_cli.api.teams import fetch_teams, fetch_children, filter_teams_by_club, sync_child_team_mapping

__all__ = [
    "fetch_article",
    "fetch_calendar_range",
    "fetch_event_detail",
    "fetch_notifications",
    "fetch_teams",
    "fetch_children",
    "filter_teams_by_club",
    "sync_child_team_mapping",
]

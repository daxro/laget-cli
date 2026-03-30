"""Tests for laget_cli.api.notifications."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from laget_cli.api.notifications import (
    _extract_relative_url,
    _extract_team_slug_from_url,
    _parse_date_from_tooltip,
    _parse_notifications,
    fetch_notifications,
    resolve_team_names,
)


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

GUESTBOOK_NOTIFICATION_HTML = """
<ul class="popoverList">
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TestClubFK-P2019/Guestbook">
        <img class="popoverList__image" src="/img/user.png" alt="Erik Johansson">
        <b>Erik Johansson</b> har skrivit i gastboken
        <small class="popoverList__info">
          <i class="icon-pencil"></i>
          <span class="tooltip" title="den 25 mars 2026 21:43"> for 4 dagar sedan</span>
          - P2019 Vast
        </small>
    </a>
  </li>
</ul>
"""

NEWS_COMMENT_NOTIFICATION_HTML = """
<ul class="popoverList">
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TeamAlpha-P2021/News/9876">
        <img class="popoverList__image" src="/img/user.png" alt="Maria Nilsson">
        <b>Maria Nilsson</b> kommenterade 'Cupen i Alvik'
        <small class="popoverList__info">
          <i class="icon-comment"></i>
          <span class="tooltip" title="den 29 mars 2026 18:45"> for 1 dag sedan</span>
          - P2021 Knatte
        </small>
    </a>
  </li>
</ul>
"""

NEWS_NOTIFICATION_HTML = """
<ul class="popoverList">
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TeamAlpha-P2021/News/1111">
        <img class="popoverList__image" src="/img/user.png" alt="Johan Andersson">
        <b>Johan Andersson</b> publicerade ett inlagg
        <small class="popoverList__info">
          <i class="icon-file"></i>
          <span class="tooltip" title="den 28 mars 2026 12:00"> for 2 dagar sedan</span>
          - P2021 Knatte
        </small>
    </a>
  </li>
</ul>
"""

RSVP_NOTIFICATION_HTML = """
<ul class="popoverList">
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TeamBeta-F2019/Event/5555">
        <img class="popoverList__image" src="/img/user.png" alt="Anna Svensson">
        <b>Anna Svensson</b> har svarat pa en aktivitet
        <small class="popoverList__info">
          <i class="icon-calendar"></i>
          <span class="tooltip" title="den 30 mars 2026 09:00"> just nu</span>
          - F2019
        </small>
    </a>
  </li>
</ul>
"""

MULTI_NOTIFICATION_HTML = """
<ul class="popoverList">
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TeamAlpha-P2021/News/9876">
        <img class="popoverList__image" src="/img/user.png" alt="Maria Nilsson">
        <b>Maria Nilsson</b> kommenterade 'Cupen i Alvik'
        <small class="popoverList__info">
          <span class="tooltip" title="den 29 mars 2026 18:45"> for 1 dag sedan</span>
        </small>
    </a>
  </li>
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TestClubFK-P2019/Guestbook">
        <img class="popoverList__image" src="/img/user.png" alt="Erik Johansson">
        <b>Erik Johansson</b> har skrivit i gastboken
        <small class="popoverList__info">
          <span class="tooltip" title="den 25 mars 2026 21:43"> for 4 dagar sedan</span>
        </small>
    </a>
  </li>
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/TeamBeta-F2019/Event/5555">
        <img class="popoverList__image" src="/img/user.png" alt="Anna Svensson">
        <b>Anna Svensson</b> har svarat pa en aktivitet
        <small class="popoverList__info">
          <span class="tooltip" title="den 30 mars 2026 09:00"> just nu</span>
        </small>
    </a>
  </li>
</ul>
"""

EMPTY_HTML = "<ul></ul>"
NO_NOTIFICATIONS_HTML = '<ul class="popoverList"></ul>'
UNKNOWN_URL_HTML = """
<ul class="popoverList">
  <li class="popoverList__itemOuter">
    <a class="popoverList__itemInner--backgroundHover" href="https://www.laget.se/SomeTeam/Weirdpage">
        <b>Someone</b> did something weird
        <small class="popoverList__info">
          <span class="tooltip" title="den 1 januari 2026 10:00"> a while ago</span>
        </small>
    </a>
  </li>
</ul>
"""


# ---------------------------------------------------------------------------
# _parse_date_from_tooltip
# ---------------------------------------------------------------------------

class TestParseDateFromTooltip:
    def test_full_date_with_time(self):
        assert _parse_date_from_tooltip("den 25 mars 2026 21:43") == "2026-03-25T21:43:00"

    def test_single_digit_day(self):
        assert _parse_date_from_tooltip("den 1 januari 2026 10:00") == "2026-01-01T10:00:00"

    def test_all_swedish_months(self):
        months = [
            ("januari", "01"), ("februari", "02"), ("mars", "03"), ("april", "04"),
            ("maj", "05"), ("juni", "06"), ("juli", "07"), ("augusti", "08"),
            ("september", "09"), ("oktober", "10"), ("november", "11"), ("december", "12"),
        ]
        for month_name, month_num in months:
            result = _parse_date_from_tooltip(f"den 15 {month_name} 2026 12:00")
            assert result == f"2026-{month_num}-15T12:00:00", f"Failed for {month_name}"

    def test_none_returns_none(self):
        assert _parse_date_from_tooltip(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date_from_tooltip("") is None

    def test_unrecognized_format_returns_none(self):
        assert _parse_date_from_tooltip("just nu") is None

    def test_case_insensitive_month(self):
        result = _parse_date_from_tooltip("den 5 Mars 2026 08:30")
        assert result == "2026-03-05T08:30:00"


# ---------------------------------------------------------------------------
# _extract_team_slug_from_url
# ---------------------------------------------------------------------------

class TestExtractTeamSlugFromUrl:
    def test_absolute_url(self):
        assert _extract_team_slug_from_url(
            "https://www.laget.se/TeamAlpha-P2021/News/9876"
        ) == "TeamAlpha-P2021"

    def test_absolute_url_guestbook(self):
        assert _extract_team_slug_from_url(
            "https://www.laget.se/TestClubFK-P2019/Guestbook"
        ) == "TestClubFK-P2019"

    def test_relative_url(self):
        assert _extract_team_slug_from_url("/TeamAlpha-P2021/News/9876") == "TeamAlpha-P2021"

    def test_relative_url_without_leading_slash(self):
        assert _extract_team_slug_from_url("TeamAlpha-P2021/News/9876") == "TeamAlpha-P2021"


# ---------------------------------------------------------------------------
# _extract_relative_url
# ---------------------------------------------------------------------------

class TestExtractRelativeUrl:
    def test_absolute_url(self):
        assert _extract_relative_url(
            "https://www.laget.se/TeamAlpha-P2021/News/9876"
        ) == "/TeamAlpha-P2021/News/9876"

    def test_already_relative(self):
        assert _extract_relative_url("/TeamAlpha-P2021/News/9876") == "/TeamAlpha-P2021/News/9876"

    def test_guestbook_url(self):
        assert _extract_relative_url(
            "https://www.laget.se/TestClubFK-P2019/Guestbook"
        ) == "/TestClubFK-P2019/Guestbook"


# ---------------------------------------------------------------------------
# _parse_notifications
# ---------------------------------------------------------------------------

class TestParseNotifications:
    def test_guestbook_notification(self):
        results = _parse_notifications(GUESTBOOK_NOTIFICATION_HTML)
        assert len(results) == 1
        n = results[0]
        assert n["type"] == "guestbook"
        assert n["author"] == "Erik Johansson"
        assert n["date"] == "2026-03-25T21:43:00"
        assert n["team_slug"] == "TestClubFK-P2019"
        assert n["url"] == "/TestClubFK-P2019/Guestbook"
        assert n["team"] is None  # resolved separately
        assert "gastboken" in n["title"].lower()

    def test_news_comment_notification(self):
        results = _parse_notifications(NEWS_COMMENT_NOTIFICATION_HTML)
        assert len(results) == 1
        n = results[0]
        assert n["type"] == "news_comment"
        assert n["author"] == "Maria Nilsson"
        assert n["date"] == "2026-03-29T18:45:00"
        assert n["team_slug"] == "TeamAlpha-P2021"
        assert n["url"] == "/TeamAlpha-P2021/News/9876"

    def test_news_notification_not_comment(self):
        results = _parse_notifications(NEWS_NOTIFICATION_HTML)
        assert len(results) == 1
        n = results[0]
        assert n["type"] == "news"
        assert n["author"] == "Johan Andersson"

    def test_rsvp_notification(self):
        results = _parse_notifications(RSVP_NOTIFICATION_HTML)
        assert len(results) == 1
        n = results[0]
        assert n["type"] == "rsvp"
        assert n["author"] == "Anna Svensson"
        assert n["date"] == "2026-03-30T09:00:00"
        assert n["team_slug"] == "TeamBeta-F2019"

    def test_multiple_notifications(self):
        results = _parse_notifications(MULTI_NOTIFICATION_HTML)
        assert len(results) == 3
        types = [n["type"] for n in results]
        assert "news_comment" in types
        assert "guestbook" in types
        assert "rsvp" in types

    def test_empty_html_returns_empty_list(self):
        assert _parse_notifications(EMPTY_HTML) == []
        assert _parse_notifications(NO_NOTIFICATIONS_HTML) == []

    def test_unknown_url_type_returns_unknown(self, capsys):
        results = _parse_notifications(UNKNOWN_URL_HTML)
        assert len(results) == 1
        assert results[0]["type"] == "unknown"
        err = capsys.readouterr().err
        assert "Weirdpage" in err or "SomeTeam" in err or "unknown" in err.lower()

    def test_all_required_fields_present(self):
        results = _parse_notifications(GUESTBOOK_NOTIFICATION_HTML)
        n = results[0]
        for field in ("date", "type", "author", "title", "team", "team_slug", "url"):
            assert field in n, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# resolve_team_names
# ---------------------------------------------------------------------------

class TestResolveTeamNames:
    def test_resolves_matching_slug(self):
        notifications = [
            {"team_slug": "TeamAlpha-P2021", "team": None},
            {"team_slug": "TeamBeta-F2019", "team": None},
        ]
        teams = [
            {"team_slug": "TeamAlpha-P2021", "name": "P2021 Knatte"},
            {"team_slug": "TeamBeta-F2019", "name": "F2019"},
        ]
        result = resolve_team_names(notifications, teams)
        assert result[0]["team"] == "P2021 Knatte"
        assert result[1]["team"] == "F2019"

    def test_unknown_slug_stays_none(self):
        notifications = [{"team_slug": "SomeOtherTeam", "team": None}]
        teams = [{"team_slug": "TeamAlpha-P2021", "name": "P2021 Knatte"}]
        result = resolve_team_names(notifications, teams)
        assert result[0]["team"] is None

    def test_mutates_in_place_and_returns_same_list(self):
        notifications = [{"team_slug": "TeamAlpha-P2021", "team": None}]
        teams = [{"team_slug": "TeamAlpha-P2021", "name": "P2021 Knatte"}]
        result = resolve_team_names(notifications, teams)
        assert result is notifications


# ---------------------------------------------------------------------------
# fetch_notifications
# ---------------------------------------------------------------------------

class TestFetchNotifications:
    def test_calls_correct_endpoint(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = GUESTBOOK_NOTIFICATION_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        results = fetch_notifications(session)
        session.get.assert_called_once()
        url_called = session.get.call_args[0][0]
        assert "/Common/Notification/GetNotifications" in url_called

    def test_sends_ajax_header(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = NO_NOTIFICATIONS_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_notifications(session)
        call_kwargs = session.get.call_args[1]
        assert call_kwargs.get("headers", {}).get("X-Requested-With") == "XMLHttpRequest"

    def test_returns_parsed_list(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = GUESTBOOK_NOTIFICATION_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        results = fetch_notifications(session)
        assert isinstance(results, list)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# CLI handler (_notifications)
# ---------------------------------------------------------------------------

class TestNotificationsCommand:
    def _run(self, argv, notifications_data, teams_data=None):
        """Helper to run the notifications CLI command with mocked dependencies."""
        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021 Knatte", "club": "TeamAlpha FK"}]

        import sys
        from io import StringIO
        from unittest.mock import patch, MagicMock
        from laget_cli.cli import main

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_notifications", return_value=notifications_data), \
             patch("laget_cli.cli.resolve_team_names", side_effect=lambda n, t: n), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue())

    def test_outputs_json_list(self):
        notifications = [
            {
                "date": "2026-03-29T18:45:00",
                "type": "news_comment",
                "author": "Maria Nilsson",
                "title": "kommenterade 'Cupen i Alvik'",
                "team": "P2021 Knatte",
                "team_slug": "TeamAlpha-P2021",
                "url": "/TeamAlpha-P2021/News/9876",
            }
        ]
        result = self._run(["notifications"], notifications)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "news_comment"

    def test_sorted_descending_by_date(self):
        notifications = [
            {"date": "2026-03-25T00:00:00", "type": "guestbook", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/Guestbook"},
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "B",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"},
            {"date": "2026-03-27T00:00:00", "type": "rsvp", "author": "C",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/Event/1"},
        ]
        result = self._run(["notifications"], notifications)
        dates = [r["date"] for r in result]
        assert dates == sorted(dates, reverse=True)

    def test_team_filter(self):
        notifications = [
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"},
            {"date": "2026-03-28T00:00:00", "type": "guestbook", "author": "B",
             "title": "t", "team": None, "team_slug": "TeamBeta-F2019", "url": "/y/Guestbook"},
        ]
        result = self._run(["notifications", "--team", "TeamAlpha"], notifications)
        assert all(r["team_slug"] == "TeamAlpha-P2021" for r in result)

    def test_since_filter(self):
        notifications = [
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"},
            {"date": "2026-01-01T00:00:00", "type": "guestbook", "author": "B",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/Guestbook"},
        ]
        result = self._run(["notifications", "--since", "2026-03-01"], notifications)
        assert all(r["date"] >= "2026-03-01" for r in result)
        assert len(result) == 1

    def test_empty_notifications_returns_empty_list(self):
        result = self._run(["notifications"], [])
        assert result == []

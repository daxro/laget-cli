"""Tests for laget_cli.api.calendar."""

import json
from unittest.mock import MagicMock, patch

import pytest

from laget_cli.api.calendar import (
    _parse_calendar_month,
    _parse_event_detail,
    _parse_location,
    _parse_maps_url,
    _parse_assembly_time,
    _parse_notes,
    _parse_rsvp,
    fetch_calendar,
    fetch_calendar_range,
    fetch_event_detail,
)


# ---------------------------------------------------------------------------
# HTML fixtures - calendar list view
# ---------------------------------------------------------------------------

CALENDAR_MONTH_HTML = """
<ul class="fullCalendar">
  <li class="fullCalendar__day monday" id="js-day-7" data-day="7">
    <div class="fullCalendar__date color1Text">
      <span class="float--right">7</span>Mån
    </div>
    <span class="fullCalendar__week">v.10</span>
    <ul class="fullCalendar__list">
      <li class="fullCalendar__item" id="js-event-7-29705518">
        <div class="fullCalendar__itemInner js-singleEvent-toggle"
             data-src="/TeamAlpha-P2021/Event/Single?eventId=29705518">
          <span class="fullCalendar__time">10:00</span>
          <p class="fullCalendar__text">
            <i class="fullCalendar__icon--green icon-calendar-empty"></i>
            Träning
          </p>
        </div>
        <span class="fullCalendar__time float--left">
          <i class="icon-long-arrow-down"></i><br>11:00
        </span>
        <div id="js-event-details-7-29705518" class="fullCalendar__details float--left"></div>
      </li>
    </ul>
    <div class="event_ad-7"></div>
  </li>
  <li class="fullCalendar__day" id="js-day-14" data-day="14">
    <div class="fullCalendar__date color1Text">
      <span class="float--right">14</span>Mån
    </div>
    <ul class="fullCalendar__list">
      <li class="fullCalendar__item" id="js-event-14-29890125">
        <div class="fullCalendar__itemInner js-singleEvent-toggle"
             data-src="/TeamAlpha-P2021/Event/Single?eventId=29890125">
          <span class="fullCalendar__time">11:45</span>
          <p class="fullCalendar__text">
            <i class="fullCalendar__icon--blue icon-calendar-empty"></i>
            Träningsmatch mot Boo FF P19:10
          </p>
        </div>
        <span class="fullCalendar__time float--left">
          <i class="icon-long-arrow-down"></i><br>13:00
        </span>
        <div id="js-event-details-14-29890125" class="fullCalendar__details float--left"></div>
      </li>
    </ul>
  </li>
</ul>
"""

CALENDAR_MULTI_EVENT_DAY_HTML = """
<ul class="fullCalendar">
  <li class="fullCalendar__day" id="js-day-29" data-day="29">
    <div class="fullCalendar__date color1Text">
      <span class="float--right">29</span>Lör
    </div>
    <ul class="fullCalendar__list">
      <li class="fullCalendar__item" id="js-event-29-11111">
        <div class="fullCalendar__itemInner js-singleEvent-toggle"
             data-src="/TeamAlpha-P2021/Event/Single?eventId=11111">
          <span class="fullCalendar__time">10:00</span>
          <p class="fullCalendar__text">
            <i class="fullCalendar__icon--green icon-calendar-empty"></i>
            Träning
          </p>
        </div>
        <span class="fullCalendar__time float--left">
          <i class="icon-long-arrow-down"></i><br>11:00
        </span>
      </li>
      <li class="fullCalendar__item" id="js-event-29-22222">
        <div class="fullCalendar__itemInner js-singleEvent-toggle"
             data-src="/TeamAlpha-P2021/Event/Single?eventId=22222">
          <span class="fullCalendar__time">11:45</span>
          <p class="fullCalendar__text">
            <i class="fullCalendar__icon--blue icon-calendar-empty"></i>
            Träningsmatch mot ABC
          </p>
        </div>
        <span class="fullCalendar__time float--left">
          <i class="icon-long-arrow-down"></i><br>13:00
        </span>
      </li>
    </ul>
  </li>
</ul>
"""

CALENDAR_WITH_AD_SLOT_HTML = """
<ul class="fullCalendar">
  <li class="fullCalendar__day" id="js-day-5" data-day="5">
    <ul class="fullCalendar__list">
      <li class="fullCalendar__item" id="js-event-5-99999">
        <div class="fullCalendar__itemInner js-singleEvent-toggle"
             data-src="/TeamAlpha-P2021/Event/Single?eventId=99999">
          <span class="fullCalendar__time">09:00</span>
          <p class="fullCalendar__text">
            <i class="fullCalendar__icon--green icon-calendar-empty"></i>
            Träning
          </p>
        </div>
        <span class="fullCalendar__time float--left">
          <i class="icon-long-arrow-down"></i><br>10:00
        </span>
      </li>
      <li class="fullCalendar__item" id="js-event-5-ad-slot">
        <div class="div-gpt-TextKalender"><!-- ad --></div>
      </li>
    </ul>
  </li>
</ul>
"""

CALENDAR_EMPTY_HTML = """<ul class="fullCalendar"></ul>"""


# ---------------------------------------------------------------------------
# HTML fixtures - event detail
# ---------------------------------------------------------------------------

DETAIL_TRAINING_WITH_MAPS_HTML = """
<input type="hidden" value="29705518" name="eventId">
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <i class="fullCalendar__icon--place icon-map-marker"></i>Sjöängsskolan
  </div>
  <a href="https://www.google.com/maps/search/?api=1&query=59.2803703%2c18.0277711" target="_blank">
    <img class="fullCalendar__map" src="https://az729104.cdn.laget.se/map.jpg">
  </a>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anteckning: </span>Inomhusträning
  </div>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anmälan: </span>
    <a href="/TeamAlpha-P2021/Rsvp/29705518/1234567">
      Alice Testsson har svarat kommer inte
    </a>
    <br>
  </div>
</div>
"""

DETAIL_MATCH_WITH_ASSEMBLY_HTML = """
<input type="hidden" value="29890125" name="eventId">
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <i class="fullCalendar__icon--place icon-map-marker"></i>Orminge BP
  </div>
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Samlingstid: </span>11:15
  </div>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anteckning: </span>Vi har tackat ja till matchen.
  </div>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anmälan: </span>
    <a href="/TeamAlpha-P2021/Rsvp/29890125/1234567">
      Alice Testsson har svarat kommer inte
    </a>
    <br>
  </div>
</div>
"""

DETAIL_TRAINING_OVRIG_PLATSINFO_HTML = """
<input type="hidden" value="29700641" name="eventId">
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <i class="fullCalendar__icon--place icon-map-marker"></i>Västertorpsskolans gymnastiksal
  </div>
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Övrig platsinfo: </span>
    Exempelgatan 1, 123 45 Stockholm https://www.google.com/maps/search/?api=1&query=59.3293%2c18.0686
  </div>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anteckning: </span>Skor för inomhusbruk!
  </div>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anmälan: </span>
    <a href="/TeamAlpha-PF2021Knatte/Rsvp/29700641/7654321">
      Bob Testsson har ej svarat
    </a>
    <br>
  </div>
</div>
"""

DETAIL_NO_RSVP_HTML = """
<input type="hidden" value="99001" name="eventId">
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <i class="fullCalendar__icon--place icon-map-marker"></i>Sporthallen
  </div>
</div>
"""

DETAIL_NO_NOTES_HTML = """
<input type="hidden" value="99002" name="eventId">
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <i class="fullCalendar__icon--place icon-map-marker"></i>Fotbollsplan
  </div>
</div>
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anmälan: </span>
    <a href="/TeamAlpha-P2021/Rsvp/99002/1234567">
      Alice Testsson har svarat kommer
    </a>
    <br>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# _parse_calendar_month tests
# ---------------------------------------------------------------------------

class TestParseCalendarMonth:
    def test_training_event_fields(self):
        events = _parse_calendar_month(CALENDAR_MONTH_HTML, 2026, 3)
        assert len(events) >= 1
        training = next(e for e in events if e["id"] == "29705518")
        assert training["type"] == "training"
        assert training["title"] == "Träning"
        assert training["date"] == "2026-03-07T10:00:00"
        assert training["start_time"] == "10:00"
        assert training["end_time"] == "11:00"
        assert training["cancelled"] is False
        assert training["location"] is None
        assert training["assembly_time"] is None
        assert training["location_url"] is None
        assert training["notes"] is None
        assert training["rsvp"] is None

    def test_match_event_type_and_title(self):
        events = _parse_calendar_month(CALENDAR_MONTH_HTML, 2026, 3)
        match = next(e for e in events if e["id"] == "29890125")
        assert match["type"] == "match"
        assert match["title"] == "Träningsmatch mot Boo FF P19:10"
        assert match["date"] == "2026-03-14T11:45:00"
        assert match["start_time"] == "11:45"
        assert match["end_time"] == "13:00"

    def test_multi_event_day_returns_both(self):
        events = _parse_calendar_month(CALENDAR_MULTI_EVENT_DAY_HTML, 2026, 4)
        assert len(events) == 2
        ids = {e["id"] for e in events}
        assert ids == {"11111", "22222"}

    def test_ad_slot_is_skipped(self):
        events = _parse_calendar_month(CALENDAR_WITH_AD_SLOT_HTML, 2026, 4)
        assert len(events) == 1
        assert events[0]["id"] == "99999"

    def test_empty_calendar_returns_empty_list(self):
        assert _parse_calendar_month(CALENDAR_EMPTY_HTML, 2026, 4) == []

    def test_date_uses_year_month_day(self):
        events = _parse_calendar_month(CALENDAR_MONTH_HTML, 2025, 11)
        training = next(e for e in events if e["id"] == "29705518")
        assert training["date"].startswith("2025-11-07T")

    def test_event_has_all_required_keys(self):
        events = _parse_calendar_month(CALENDAR_MONTH_HTML, 2026, 3)
        required = {"id", "type", "title", "cancelled", "date", "start_time", "end_time",
                    "location", "assembly_time", "location_url", "notes", "rsvp"}
        for event in events:
            assert required <= set(event.keys()), f"Missing keys in event: {set(required) - set(event.keys())}"


# ---------------------------------------------------------------------------
# _parse_event_detail tests
# ---------------------------------------------------------------------------

class TestParseEventDetail:
    def test_training_with_maps(self):
        result = _parse_event_detail(DETAIL_TRAINING_WITH_MAPS_HTML, "29705518", "TeamAlpha-P2021")
        assert result["id"] == "29705518"
        assert result["team_slug"] == "TeamAlpha-P2021"
        assert result["location"] == "Sjöängsskolan"
        assert "google.com/maps/search" in result["location_url"]
        assert result["assembly_time"] is None
        assert result["notes"] == "Inomhusträning"
        assert result["rsvp"]["my_response"] == "no"
        assert result["rsvp"]["yes"] is None
        assert result["rsvp"]["no"] is None
        assert result["rsvp"]["unanswered"] is None

    def test_null_fields_for_list_view_data(self):
        result = _parse_event_detail(DETAIL_TRAINING_WITH_MAPS_HTML, "29705518", "TeamAlpha-P2021")
        assert result["type"] is None
        assert result["title"] is None
        assert result["date"] is None
        assert result["start_time"] is None
        assert result["end_time"] is None
        assert result["team"] is None

    def test_match_with_assembly_time(self):
        result = _parse_event_detail(DETAIL_MATCH_WITH_ASSEMBLY_HTML, "29890125", "TeamAlpha-P2021")
        assert result["location"] == "Orminge BP"
        assert result["location_url"] is None
        assert result["assembly_time"] == "11:15"
        assert "Vi har tackat ja" in result["notes"]
        assert result["rsvp"]["my_response"] == "no"

    def test_ovrig_platsinfo_inline_maps_url(self):
        result = _parse_event_detail(DETAIL_TRAINING_OVRIG_PLATSINFO_HTML, "29700641", "TeamAlpha-PF2021Knatte")
        assert result["location"] == "Västertorpsskolans gymnastiksal"
        assert "google.com/maps/search" in result["location_url"]
        assert result["rsvp"]["my_response"] == "unanswered"
        assert "inomhusbruk" in result["notes"]

    def test_rsvp_kommer(self):
        result = _parse_event_detail(DETAIL_NO_NOTES_HTML, "99002", "TeamAlpha-P2021")
        assert result["rsvp"]["my_response"] == "yes"

    def test_no_rsvp_section_returns_none(self):
        result = _parse_event_detail(DETAIL_NO_RSVP_HTML, "99001", "TeamAlpha-P2021")
        assert result["rsvp"] is None

    def test_no_notes_returns_none(self):
        result = _parse_event_detail(DETAIL_NO_NOTES_HTML, "99002", "TeamAlpha-P2021")
        assert result["notes"] is None



# ---------------------------------------------------------------------------
# Helper parser unit tests
# ---------------------------------------------------------------------------

class TestParseLocation:
    def test_extracts_location(self):
        assert _parse_location(DETAIL_TRAINING_WITH_MAPS_HTML) == "Sjöängsskolan"

    def test_no_location_returns_none(self):
        assert _parse_location("<div>nothing here</div>") is None

    def test_multi_word_location(self):
        assert _parse_location(DETAIL_TRAINING_OVRIG_PLATSINFO_HTML) == "Västertorpsskolans gymnastiksal"


class TestParseMapsUrl:
    def test_href_maps_url(self):
        url = _parse_maps_url(DETAIL_TRAINING_WITH_MAPS_HTML)
        assert url == "https://www.google.com/maps/search/?api=1&query=59.2803703%2c18.0277711"

    def test_no_maps_returns_none(self):
        assert _parse_maps_url(DETAIL_MATCH_WITH_ASSEMBLY_HTML) is None

    def test_ovrig_platsinfo_inline_url(self):
        url = _parse_maps_url(DETAIL_TRAINING_OVRIG_PLATSINFO_HTML)
        assert url is not None
        assert "google.com/maps/search" in url


class TestParseAssemblyTime:
    def test_extracts_assembly_time(self):
        assert _parse_assembly_time(DETAIL_MATCH_WITH_ASSEMBLY_HTML) == "11:15"

    def test_no_assembly_time_returns_none(self):
        assert _parse_assembly_time(DETAIL_TRAINING_WITH_MAPS_HTML) is None


class TestParseNotes:
    def test_extracts_notes(self):
        assert _parse_notes(DETAIL_TRAINING_WITH_MAPS_HTML) == "Inomhusträning"

    def test_no_notes_returns_none(self):
        assert _parse_notes(DETAIL_NO_NOTES_HTML) is None

    def test_multi_word_notes(self):
        result = _parse_notes(DETAIL_MATCH_WITH_ASSEMBLY_HTML)
        assert result is not None
        assert "Vi har tackat ja" in result


class TestParseRsvp:
    def test_kommer_inte_is_no(self):
        result = _parse_rsvp(DETAIL_TRAINING_WITH_MAPS_HTML)
        assert result["my_response"] == "no"

    def test_kommer_is_yes(self):
        result = _parse_rsvp(DETAIL_NO_NOTES_HTML)
        assert result["my_response"] == "yes"

    def test_har_ej_svarat_is_unanswered(self):
        result = _parse_rsvp(DETAIL_TRAINING_OVRIG_PLATSINFO_HTML)
        assert result["my_response"] == "unanswered"

    def test_no_rsvp_returns_none(self):
        assert _parse_rsvp(DETAIL_NO_RSVP_HTML) is None



# ---------------------------------------------------------------------------
# fetch_calendar tests
# ---------------------------------------------------------------------------

class TestFetchCalendar:
    def test_calls_correct_endpoint(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_MONTH_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_calendar(session, "TeamAlpha-P2021", 2026, 3)
        session.get.assert_called_once()
        url = session.get.call_args[0][0]
        assert "TeamAlpha-P2021/Event/FilterEvents" in url

    def test_sends_ajax_header(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_EMPTY_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_calendar(session, "TeamAlpha-P2021", 2026, 3)
        kwargs = session.get.call_args[1]
        assert kwargs.get("headers", {}).get("X-Requested-With") == "XMLHttpRequest"

    def test_passes_year_month_params(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_EMPTY_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_calendar(session, "TeamAlpha-P2021", 2026, 4)
        kwargs = session.get.call_args[1]
        params = kwargs.get("params", {})
        assert params["year"] == 2026
        assert params["month"] == 4


# ---------------------------------------------------------------------------
# fetch_calendar_range tests
# ---------------------------------------------------------------------------

class TestFetchCalendarRange:
    def _make_session(self, events_by_month):
        """Return a session mock that returns different events per month call."""
        session = MagicMock()

        def side_effect(url, params=None, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            month = (params or {}).get("month", 1)
            resp.text = events_by_month.get(month, CALENDAR_EMPTY_HTML)
            return resp

        session.get.side_effect = side_effect
        return session

    def test_single_month_range(self):
        session = self._make_session({3: CALENDAR_MONTH_HTML})
        events = fetch_calendar_range(session, "TeamAlpha-P2021", "2026-03-01", "2026-03-31")
        assert len(events) >= 1
        assert session.get.call_count == 1

    def test_two_month_range_fetches_both(self):
        session = self._make_session({3: CALENDAR_MONTH_HTML, 4: CALENDAR_EMPTY_HTML})
        fetch_calendar_range(session, "TeamAlpha-P2021", "2026-03-15", "2026-04-15")
        assert session.get.call_count == 2

    def test_year_boundary_range(self):
        session = self._make_session({12: CALENDAR_EMPTY_HTML, 1: CALENDAR_EMPTY_HTML})
        fetch_calendar_range(session, "TeamAlpha-P2021", "2025-12-15", "2026-01-15")
        assert session.get.call_count == 2

    def test_deduplicates_by_event_id(self):
        # Same month HTML served for both months - same event IDs appear twice
        session = self._make_session({3: CALENDAR_MONTH_HTML, 4: CALENDAR_MONTH_HTML})
        events = fetch_calendar_range(session, "TeamAlpha-P2021", "2026-03-01", "2026-04-30")
        ids = [e["id"] for e in events]
        assert len(ids) == len(set(ids))

    def test_sorted_by_date_ascending(self):
        session = self._make_session({3: CALENDAR_MULTI_EVENT_DAY_HTML})
        events = fetch_calendar_range(session, "TeamAlpha-P2021", "2026-03-01", "2026-03-31")
        dates = [e["date"] for e in events]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# fetch_event_detail tests
# ---------------------------------------------------------------------------

class TestFetchEventDetail:
    def test_calls_correct_endpoint(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = DETAIL_TRAINING_WITH_MAPS_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_event_detail(session, "TeamAlpha-P2021", "29705518")
        url = session.get.call_args[0][0]
        assert "TeamAlpha-P2021/Event/Single" in url

    def test_sends_ajax_header(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = DETAIL_TRAINING_WITH_MAPS_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_event_detail(session, "TeamAlpha-P2021", "29705518")
        kwargs = session.get.call_args[1]
        assert kwargs.get("headers", {}).get("X-Requested-With") == "XMLHttpRequest"

    def test_passes_event_id_param(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = DETAIL_TRAINING_WITH_MAPS_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        fetch_event_detail(session, "TeamAlpha-P2021", "29705518")
        kwargs = session.get.call_args[1]
        assert kwargs.get("params", {}).get("eventId") == "29705518"



# ---------------------------------------------------------------------------
# CLI handler tests
# ---------------------------------------------------------------------------

class TestCalendarCommand:
    def _run(self, argv, events_data=None, teams_data=None):
        from io import StringIO
        from laget_cli.cli import main

        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "TeamAlpha FK"}]
        if events_data is None:
            events_data = []

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_calendar_range", return_value=events_data), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue())

    def test_empty_events_returns_empty_list(self):
        result = self._run(["calendar"])
        assert result == []

    def test_non_empty_output_has_team_structure(self):
        events = [
            {
                "id": "123", "type": "training", "title": "Träning",
                "cancelled": False, "date": "2026-04-01T10:00:00",
                "start_time": "10:00", "end_time": "11:00",
                "location": None, "assembly_time": None, "location_url": None,
                "notes": None, "rsvp": None,
            }
        ]
        result = self._run(["calendar"], events_data=events)
        assert len(result) == 1
        assert result[0]["team_slug"] == "TeamAlpha-P2021"
        assert result[0]["team"] == "P2021"
        assert len(result[0]["events"]) == 1

    def test_team_filter_no_match_exits(self):
        import sys
        with pytest.raises(SystemExit):
            self._run(["calendar", "--team", "NoSuchTeam"])

    def test_team_filter_matches_substring(self):
        events = [
            {
                "id": "123", "type": "training", "title": "Träning",
                "cancelled": False, "date": "2026-04-01T10:00:00",
                "start_time": "10:00", "end_time": "11:00",
                "location": None, "assembly_time": None, "location_url": None,
                "notes": None, "rsvp": None,
            }
        ]
        teams = [
            {"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "FK"},
            {"team_slug": "TeamBeta-F2019", "name": "F2019", "club": "FK"},
        ]
        result = self._run(["calendar", "--team", "TeamAlpha"], events_data=events, teams_data=teams)
        # Only TeamAlpha team should be in output (TeamBeta filtered out before fetch)
        team_slugs = [r["team_slug"] for r in result]
        assert all("TeamAlpha" in slug for slug in team_slugs)


class TestEventCommand:
    def _run(self, argv, detail_data=None, teams_data=None):
        from io import StringIO
        from laget_cli.cli import main

        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "FK"}]
        if detail_data is None:
            detail_data = {
                "id": "29705518", "team": None, "team_slug": "TeamAlpha-P2021",
                "type": None, "title": None, "cancelled": False,
                "date": None, "start_time": None, "end_time": None,
                "assembly_time": None, "location": "Sjöängsskolan",
                "location_url": None, "notes": None, "rsvp": None, "responses": [],
            }

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_event_detail", return_value=detail_data), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue())

    def test_outputs_event_dict(self):
        result = self._run(["event", "--team", "TeamAlpha-P2021", "29705518"])
        assert isinstance(result, dict)
        assert result["location"] == "Sjöängsskolan"

    def test_team_name_resolved(self):
        result = self._run(["event", "--team", "TeamAlpha-P2021", "29705518"])
        assert result["team"] == "P2021"

    def test_unknown_team_exits(self):
        with pytest.raises(SystemExit):
            self._run(["event", "--team", "NoSuchTeam", "12345"])

    def test_team_substring_match(self):
        result = self._run(["event", "--team", "TeamAlpha", "29705518"])
        assert result["team"] == "P2021"


# ---------------------------------------------------------------------------
# fetch_calendar_range with None dates
# ---------------------------------------------------------------------------

class TestFetchCalendarRangeNone:
    def test_none_start_uses_reasonable_default(self):
        """fetch_calendar_range with None start_date should not crash."""
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_EMPTY_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        events = fetch_calendar_range(session, "TeamAlpha-P2021", None, "2026-04-30")
        assert isinstance(events, list)

    def test_none_end_uses_reasonable_default(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_EMPTY_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        events = fetch_calendar_range(session, "TeamAlpha-P2021", "2026-03-01", None)
        assert isinstance(events, list)


# ---------------------------------------------------------------------------
# CLI handler - calendar --since all / --until all
# ---------------------------------------------------------------------------

class TestCalendarSinceAll:
    """Regression tests for --since all / --until all (previously crashed with TypeError)."""

    def _run(self, argv, events_data=None, teams_data=None):
        from io import StringIO
        from laget_cli.cli import main

        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "TeamAlpha FK"}]
        if events_data is None:
            events_data = []

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_calendar_range", return_value=events_data), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue())

    def test_since_all_does_not_crash(self):
        """calendar --since all should not crash with TypeError."""
        result = self._run(["calendar", "--since", "all"])
        assert isinstance(result, list)

    def test_until_all_does_not_crash(self):
        """calendar --until all should not crash with TypeError."""
        result = self._run(["calendar", "--until", "all"])
        assert isinstance(result, list)

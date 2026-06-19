"""Tests for laget_cli.api.calendar."""

import json
from datetime import date, timedelta
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
    _parse_rsvp_form,
    fetch_calendar,
    fetch_calendar_range,
    fetch_event_detail,
    submit_rsvp,
)
from laget_cli.errors import ParseError


FROZEN_TODAY = date(2026, 3, 15)


class FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day)


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

DETAIL_MULTIPLE_RSVP_HTML = """
<div class="fullCalendar__info">
  <div class="fullCalendar__text">
    <span class="fullCalendar__infoLabel">Anmälan: </span>
    <a href="/TeamAlpha-P2021/Rsvp/99003/1234567">Alice Testsson har svarat kommer</a>
    <a href="/TeamAlpha-P2021/Rsvp/99003/7654321">Bob Testsson har ej svarat</a>
  </div>
</div>
"""

RSVP_FORM_HTML = """
<form id="js-rsvp-form" action="/Common/Event/SaveEventAnswer" method="post">
  <input type="hidden" id="EventId" name="EventId" value="29705518">
  <input type="hidden" id="EventUserId" name="EventUserId" value="335227096">
  <input type="hidden" id="IsChild" name="IsChild" value="True">
  <input type="hidden" id="ChildIdKey" name="ChildIdKey" value="abc123">
  <input type="hidden" id="EventSiteName" name="EventSiteName" value="TeamAlpha-P2021">
  <input type="hidden" name="siteName" value="TeamAlpha-P2021">
  <input type="hidden" id="WillAttend" name="WillAttend" value="True">
  <input type="submit" value="Spara">
</form>
"""

RSVP_FORM_WITH_COMMENT_HTML = """
<form id="js-rsvp-form" action="/Common/Event/SaveEventAnswer" method="post">
  <input type="hidden" id="EventId" name="EventId" value="29705518">
  <input type="hidden" id="EventUserId" name="EventUserId" value="335227096">
  <input type="hidden" id="WillAttend" name="WillAttend" value="True">
  <textarea name="Comment">old comment</textarea>
</form>
"""

RSVP_WRAPPER_HTML = """
<div id="rsvpModal" data-rsvp-event="29705518" data-rsvp-user="1234567">
  <a class="js-rsvp-invites eventList__itemInner"
     href="/Common/Rsvp/ModalContent?pk=29705518&amp;childId=1234567&amp;site=TeamAlpha-P2021"
     data-eventid="29705518"
     data-eventuserid="1234567">Training invite</a>
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
        assert result["url"] == "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567"

    def test_kommer_is_yes(self):
        result = _parse_rsvp(DETAIL_NO_NOTES_HTML)
        assert result["my_response"] == "yes"

    def test_har_ej_svarat_is_unanswered(self):
        result = _parse_rsvp(DETAIL_TRAINING_OVRIG_PLATSINFO_HTML)
        assert result["my_response"] == "unanswered"

    def test_no_rsvp_returns_none(self):
        assert _parse_rsvp(DETAIL_NO_RSVP_HTML) is None

    def test_absolute_rsvp_url_is_preserved(self):
        html = DETAIL_NO_NOTES_HTML.replace(
            'href="/TeamAlpha-P2021/Rsvp/99002/1234567"',
            'href="https://www.laget.se/TeamAlpha-P2021/Rsvp/99002/1234567"',
        )
        result = _parse_rsvp(html)
        assert result["url"] == "https://www.laget.se/TeamAlpha-P2021/Rsvp/99002/1234567"

    def test_multiple_rsvp_links_raise_parse_error(self):
        with pytest.raises(ParseError):
            _parse_rsvp(DETAIL_MULTIPLE_RSVP_HTML)


class TestParseRsvpForm:
    def test_parses_scoped_form_fields(self):
        result = _parse_rsvp_form(f"<form id='other'><input name='EventId' value='wrong'></form>{RSVP_FORM_HTML}", "29705518")
        assert result["action"] == "/Common/Event/SaveEventAnswer"
        assert result["fields"]["EventId"] == "29705518"
        assert result["fields"]["EventUserId"] == "335227096"
        assert result["fields"]["WillAttend"] == "True"

    def test_event_id_mismatch_raises(self):
        with pytest.raises(ParseError):
            _parse_rsvp_form(RSVP_FORM_HTML, "999")

    def test_missing_required_field_raises(self):
        html = RSVP_FORM_HTML.replace('name="EventUserId"', 'name="MissingEventUserId"')
        with pytest.raises(ParseError):
            _parse_rsvp_form(html, "29705518")

    def test_missing_form_action_raises(self):
        html = RSVP_FORM_HTML.replace(' action="/Common/Event/SaveEventAnswer"', "")
        with pytest.raises(ParseError):
            _parse_rsvp_form(html, "29705518")

    def test_multiple_forms_raise(self):
        with pytest.raises(ParseError):
            _parse_rsvp_form(RSVP_FORM_HTML + RSVP_FORM_HTML, "29705518")


class TestSubmitRsvp:
    def _session(self, html=RSVP_FORM_HTML):
        session = MagicMock()
        get_resp = MagicMock()
        get_resp.text = html
        get_resp.raise_for_status = MagicMock()
        post_resp = MagicMock()
        post_resp.raise_for_status = MagicMock()
        session.get.return_value = get_resp
        session.post.return_value = post_resp
        return session, post_resp

    def test_posts_yes_with_preserved_fields(self):
        session, _ = self._session()
        submit_rsvp(session, "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567", "yes", event_id="29705518")

        session.post.assert_called_once()
        url = session.post.call_args[0][0]
        data = session.post.call_args[1]["data"]
        headers = session.post.call_args[1]["headers"]
        assert url == "https://www.laget.se/Common/Event/SaveEventAnswer"
        assert data["EventUserId"] == "335227096"
        assert data["ChildIdKey"] == "abc123"
        assert data["WillAttend"] == "True"
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_posts_no(self):
        session, _ = self._session()
        submit_rsvp(session, "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567", "no", event_id="29705518")
        assert session.post.call_args[1]["data"]["WillAttend"] == "False"

    def test_posts_comment_when_textarea_exists(self):
        session, _ = self._session(RSVP_FORM_WITH_COMMENT_HTML)
        submit_rsvp(
            session,
            "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567",
            "no",
            comment="Sjuk idag",
            event_id="29705518",
        )
        assert session.post.call_args[1]["data"]["Comment"] == "Sjuk idag"

    def test_rejects_comment_without_textarea(self):
        session, _ = self._session()
        with pytest.raises(ParseError):
            submit_rsvp(
                session,
                "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567",
                "yes",
                comment="Sjuk idag",
                event_id="29705518",
            )

    def test_uses_timeout_on_get_and_post(self):
        session, _ = self._session()
        submit_rsvp(session, "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567", "yes", event_id="29705518")
        assert "timeout" in session.get.call_args[1]
        assert "timeout" in session.post.call_args[1]

    def test_follows_modal_link_when_rsvp_page_wraps_form(self):
        session = MagicMock()
        wrapper_resp = MagicMock()
        wrapper_resp.text = RSVP_WRAPPER_HTML
        wrapper_resp.raise_for_status = MagicMock()
        form_resp = MagicMock()
        form_resp.text = RSVP_FORM_HTML
        form_resp.raise_for_status = MagicMock()
        post_resp = MagicMock()
        post_resp.raise_for_status = MagicMock()
        session.get.side_effect = [wrapper_resp, form_resp]
        session.post.return_value = post_resp

        submit_rsvp(session, "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567", "yes", event_id="29705518")

        assert session.get.call_count == 2
        assert session.get.call_args_list[1][0][0] == (
            "https://www.laget.se/Common/Rsvp/ModalContent?pk=29705518&childId=1234567&site=TeamAlpha-P2021"
        )
        assert session.post.call_args[1]["data"]["WillAttend"] == "True"



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

    def test_limit_stops_fetching_more_months(self):
        session = self._make_session({3: CALENDAR_MULTI_EVENT_DAY_HTML, 4: CALENDAR_MONTH_HTML})
        events = fetch_calendar_range(
            session,
            "TeamAlpha-P2021",
            "2026-03-01",
            "2026-04-30",
            limit=1,
        )
        assert len(events) == 1
        assert session.get.call_count == 1

    def test_range_over_24_months_is_rejected(self):
        session = self._make_session({})
        with pytest.raises(ValueError, match="at most 24 months"):
            fetch_calendar_range(session, "TeamAlpha-P2021", "2024-01-01", "2026-01-01")


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

    def test_empty_events_preserve_team_envelope(self):
        result = self._run(["calendar"])
        assert result == [
            {"team": "P2021", "team_slug": "TeamAlpha-P2021", "events": []},
        ]

    def test_non_empty_output_has_team_structure(self):
        event_date = "2026-03-16"
        events = [
            {
                "id": "123", "type": "training", "title": "Träning",
                "cancelled": False, "date": f"{event_date}T10:00:00",
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

    def test_fields_filter_events_and_preserve_team_envelope(self):
        events = [
            {
                "id": "123", "type": "training", "title": "Träning",
                "cancelled": False, "date": "2026-07-01T10:00:00",
                "start_time": "10:00", "end_time": "11:00",
                "location": None, "assembly_time": None, "location_url": None,
                "notes": None, "rsvp": None,
            }
        ]
        result = self._run(["calendar", "--fields", "date,type"], events_data=events)
        assert set(result[0]) == {"team", "team_slug", "events"}
        assert set(result[0]["events"][0]) == {"date", "type"}


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


class TestRsvpCommand:
    def _detail(self, response="unanswered", rsvp_url="https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567"):
        return {
            "id": "29705518", "team": None, "team_slug": "TeamAlpha-P2021",
            "type": None, "title": None, "cancelled": False,
            "date": None, "start_time": None, "end_time": None,
            "assembly_time": None, "location": "Sjöängsskolan",
            "location_url": None, "notes": None,
            "rsvp": {
                "yes": None,
                "no": None,
                "unanswered": None,
                "my_response": response,
                "url": rsvp_url,
            } if rsvp_url else None,
            "responses": [],
        }

    def _run(self, argv, details=None, teams_data=None):
        from io import StringIO
        from laget_cli.cli import main

        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "FK"}]
        if details is None:
            details = [self._detail("unanswered"), self._detail("yes")]

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_event_detail", side_effect=details), \
             patch("laget_cli.cli.submit_rsvp") as mock_submit, \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue()), mock_submit

    def test_submits_refetches_verifies_and_outputs_json(self):
        result, mock_submit = self._run(["rsvp", "--team", "TeamAlpha-P2021", "29705518", "yes"])
        assert result["team"] == "P2021"
        assert result["rsvp"]["my_response"] == "yes"
        mock_submit.assert_called_once()
        assert mock_submit.call_args[0][1] == "https://www.laget.se/TeamAlpha-P2021/Rsvp/29705518/1234567"
        assert mock_submit.call_args[0][2] == "yes"
        assert mock_submit.call_args[1]["event_id"] == "29705518"

    def test_passes_comment_to_submit(self):
        _, mock_submit = self._run(["rsvp", "--team", "TeamAlpha-P2021", "29705518", "no", "--comment", "Sjuk idag"],
                                   details=[self._detail("unanswered"), self._detail("no")])
        assert mock_submit.call_args[1]["comment"] == "Sjuk idag"

    def test_fields_filters_output(self):
        result, _ = self._run(["rsvp", "--team", "TeamAlpha-P2021", "29705518", "yes", "--fields", "id,rsvp"])
        assert set(result.keys()) == {"id", "rsvp"}

    def test_requires_exact_team_slug(self):
        with pytest.raises(SystemExit) as exc:
            self._run(["rsvp", "--team", "TeamAlpha", "29705518", "yes"])
        assert exc.value.code == 4

    def test_unknown_team_exits_4(self):
        with pytest.raises(SystemExit) as exc:
            self._run(["rsvp", "--team", "NoSuchTeam", "29705518", "yes"])
        assert exc.value.code == 4

    def test_no_rsvp_link_exits_4(self):
        with pytest.raises(SystemExit) as exc:
            self._run(["rsvp", "--team", "TeamAlpha-P2021", "29705518", "yes"], details=[self._detail(rsvp_url=None)])
        assert exc.value.code == 4

    def test_verification_mismatch_exits_1(self):
        with pytest.raises(SystemExit) as exc:
            self._run(["rsvp", "--team", "TeamAlpha-P2021", "29705518", "yes"],
                      details=[self._detail("unanswered"), self._detail("no")])
        assert exc.value.code == 1

    def test_invalid_response_exits_2(self):
        from laget_cli.cli import main

        with patch("sys.argv", ["laget", "rsvp", "--team", "TeamAlpha-P2021", "29705518", "maybe"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# fetch_calendar_range with None dates
# ---------------------------------------------------------------------------

class TestFetchCalendarRangeNone:
    def test_none_start_uses_previous_year_months(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_EMPTY_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        with patch("laget_cli.api.calendar.date", FrozenDate):
            fetch_calendar_range(session, "TeamAlpha-P2021", None, "2026-04-30")

        requested_months = [
            (call.kwargs["params"]["year"], call.kwargs["params"]["month"])
            for call in session.get.call_args_list
        ]
        assert requested_months == [
            (2025, 3),
            (2025, 4),
            (2025, 5),
            (2025, 6),
            (2025, 7),
            (2025, 8),
            (2025, 9),
            (2025, 10),
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
            (2026, 3),
            (2026, 4),
        ]

    def test_none_end_uses_next_year_months(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CALENDAR_EMPTY_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        with patch("laget_cli.api.calendar.date", FrozenDate):
            fetch_calendar_range(session, "TeamAlpha-P2021", "2026-03-01", None)

        requested_months = [
            (call.kwargs["params"]["year"], call.kwargs["params"]["month"])
            for call in session.get.call_args_list
        ]
        assert requested_months == [
            (2026, 3),
            (2026, 4),
            (2026, 5),
            (2026, 6),
            (2026, 7),
            (2026, 8),
            (2026, 9),
            (2026, 10),
            (2026, 11),
            (2026, 12),
            (2027, 1),
            (2027, 2),
            (2027, 3),
        ]


# ---------------------------------------------------------------------------
# CLI handler - calendar --since all / --until all
# ---------------------------------------------------------------------------

class TestCalendarSinceAll:
    """Regression tests for bounded --since all / --until all ranges."""

    def _run_and_capture_range(self, argv, events_data=None, teams_data=None):
        from io import StringIO
        from laget_cli.cli import main

        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "TeamAlpha FK"}]
        if events_data is None:
            events_data = []

        ranges = []

        def capture_range(session, team_slug, since, until, limit=None):
            ranges.append((team_slug, since, until, limit))
            return events_data

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_calendar_range", side_effect=capture_range), \
             patch("laget_cli.cli.date", FrozenDate), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue()), ranges

    def test_since_all_uses_previous_year_through_default_window(self):
        result, ranges = self._run_and_capture_range(["calendar", "--since", "all"])
        assert result == [
            {"team": "P2021", "team_slug": "TeamAlpha-P2021", "events": []},
        ]
        assert ranges == [("TeamAlpha-P2021", "2025-03-15", "2026-04-14", None)]

    def test_until_all_uses_current_day_through_next_year(self):
        result, ranges = self._run_and_capture_range(["calendar", "--until", "all"])
        assert result == [
            {"team": "P2021", "team_slug": "TeamAlpha-P2021", "events": []},
        ]
        assert ranges == [("TeamAlpha-P2021", "2026-03-15", "2027-03-15", None)]

    def test_since_all_and_until_all_stay_bounded_to_24_months(self):
        result, ranges = self._run_and_capture_range(["calendar", "--since", "all", "--until", "all"])
        assert result == [
            {"team": "P2021", "team_slug": "TeamAlpha-P2021", "events": []},
        ]
        assert ranges == [("TeamAlpha-P2021", "2025-03-15", "2027-02-28", None)]

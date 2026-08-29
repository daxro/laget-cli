"""Contract tests for the JSON calendar/event API."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from laget_cli.api.calendar import (
    API_BASE_URL,
    _epoch_to_local_iso,
    fetch_calendar,
    fetch_calendar_range,
    fetch_event_detail,
    submit_rsvp,
)
from laget_cli.errors import ParseError
from laget_cli.session import HTTP_TIMEOUT


TEAM_SLUG = "TeamAlpha-P2021"
SITE_ID = "44"
USER_ID = "7654321"


def epoch_ms(iso_utc):
    return int(datetime.fromisoformat(iso_utc).replace(tzinfo=timezone.utc).timestamp() * 1000)


def api_event(event_id, start, *, site_id=SITE_ID, title="Träning", **overrides):
    event = {
        "id": int(event_id),
        "site": {
            "id": int(site_id),
            "name": "Team Alpha",
            "url": f"https://www.laget.se/{TEAM_SLUG}",
            "displayNames": ["P2021"],
        },
        "dateStart": epoch_ms(start),
        "dateEnd": epoch_ms(start) + 3_600_000,
        "title": title,
        "eventType": 2,
        "body": "Ta med vatten<br>och boll",
        "place": "Sjöängsskolan",
        "assembly": epoch_ms(start) - 1_800_000,
        "rsvp": True,
        "userRsvp": {
            "attending": 1,
            "attendingAssembly": True,
            "numCarSeats": 2,
            "answer": "Tidigare svar",
            "reason": "",
        },
    }
    event.update(overrides)
    return event


def response(payload):
    result = MagicMock()
    result.json.return_value = payload
    return result


def session_with(*payloads):
    session = MagicMock()
    session.user_id = USER_ID
    session.team_site_ids = {TEAM_SLUG: SITE_ID}
    session.get.side_effect = [response(payload) for payload in payloads]
    return session


class TestEpochNormalization:
    def test_uses_stockholm_summer_time(self):
        assert _epoch_to_local_iso(epoch_ms("2026-06-15T15:00:00")) == "2026-06-15T17:00:00"

    def test_uses_stockholm_winter_time(self):
        assert _epoch_to_local_iso(epoch_ms("2026-01-15T15:00:00")) == "2026-01-15T16:00:00"

    def test_tolerates_iso_and_invalid_values(self):
        assert _epoch_to_local_iso("2026-06-15T15:00:00Z") == "2026-06-15T17:00:00"
        assert _epoch_to_local_iso("not-a-date") is None


class TestCalendarRange:
    @patch("laget_cli.api.calendar.date")
    def test_fetches_past_and_upcoming_filters_site_deduplicates_and_sorts(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.fromisoformat.side_effect = date.fromisoformat
        events = [
            api_event(2, "2026-06-20T08:00:00"),
            api_event(1, "2026-06-10T08:00:00"),
            api_event(9, "2026-06-12T08:00:00", site_id="99"),
        ]
        session = session_with({"events": events[:2]}, {"events": events[1:]})

        result = fetch_calendar_range(
            session, TEAM_SLUG, "2026-06-01", "2026-06-30", detail_fields=set()
        )

        assert [event["id"] for event in result] == ["1", "2"]
        assert result[0] == {
            "id": "1",
            "type": "training",
            "title": "Träning",
            "cancelled": False,
            "date": "2026-06-10T10:00:00",
            "start_time": "10:00",
            "end_time": "11:00",
            "location": None,
            "assembly_time": None,
            "location_url": None,
            "notes": None,
            "rsvp": None,
        }
        assert [item.args[0].rsplit("/", 1)[-1] for item in session.get.call_args_list] == [
            "past",
            "upcoming",
        ]
        assert all(item.kwargs["params"] == {"pageIndex": 0, "pageSize": 50} for item in session.get.call_args_list)

    @patch("laget_cli.api.calendar.date")
    def test_reuses_user_global_pages_across_teams(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.fromisoformat.side_effect = date.fromisoformat
        second_slug = "TeamBeta-F2020"
        second_site = "55"
        session = MagicMock()
        session.user_id = USER_ID
        session.team_site_ids = {TEAM_SLUG: SITE_ID, second_slug: second_site}
        page = {
            "events": [
                api_event(1, "2026-06-10T08:00:00", site_id=SITE_ID),
                api_event(2, "2026-06-20T08:00:00", site_id=second_site),
            ]
        }
        session.get.side_effect = [response(page), response(page)]

        first = fetch_calendar_range(session, TEAM_SLUG, "2026-06-01", "2026-06-30")
        second = fetch_calendar_range(session, second_slug, "2026-06-01", "2026-06-30")

        assert [item["id"] for item in first] == ["1"]
        assert [item["id"] for item in second] == ["2"]
        assert session.get.call_count == 2

    @patch("laget_cli.api.calendar.date")
    def test_future_range_uses_upcoming_only_and_limit_after_sort(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.fromisoformat.side_effect = date.fromisoformat
        session = session_with({"events": [
            api_event(2, "2026-07-20T08:00:00"),
            api_event(1, "2026-07-10T08:00:00"),
        ]})

        result = fetch_calendar_range(session, TEAM_SLUG, "2026-07-01", "2026-07-31", limit=1)

        assert [event["id"] for event in result] == ["1"]
        assert session.get.call_count == 1
        assert session.get.call_args.args[0].endswith("/upcoming")

    @patch("laget_cli.api.calendar.date")
    def test_full_page_continues_until_short_page(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.fromisoformat.side_effect = date.fromisoformat
        first = [api_event(i, "2026-07-01T08:00:00") for i in range(1, 51)]
        session = session_with({"events": first}, {"events": [api_event(51, "2026-07-02T08:00:00")]})

        result = fetch_calendar_range(session, TEAM_SLUG, "2026-07-01", "2026-07-31")

        assert len(result) == 51
        assert session.get.call_args_list[1].kwargs["params"]["pageIndex"] == 1

    def test_rejects_more_than_24_calendar_months(self):
        session = session_with()
        with pytest.raises(ValueError, match="at most 24 months"):
            fetch_calendar_range(session, TEAM_SLUG, "2024-01-01", "2026-01-01")

    @patch("laget_cli.api.calendar.fetch_calendar_range", return_value=[])
    def test_single_month_compatibility_wrapper(self, fetch_range):
        fetch_calendar(MagicMock(), TEAM_SLUG, 2026, 2)
        assert fetch_range.call_args.args[2:] == ("2026-02-01", "2026-02-28")

    def test_malformed_event_envelope_is_parse_error(self):
        session = session_with({"items": []})
        with pytest.raises(ParseError, match="missing events"):
            fetch_calendar_range(session, TEAM_SLUG, "2099-01-01", "2099-01-02")


class TestEventDetail:
    def test_calls_json_endpoint_and_normalizes_full_public_shape(self):
        raw = api_event(29705518, "2026-06-20T08:00:00")
        session = session_with({"event": raw})

        detail = fetch_event_detail(session, TEAM_SLUG, "29705518")

        session.get.assert_called_once_with(
            f"{API_BASE_URL}/v4/events/29705518",
            params={"siteId": SITE_ID},
            timeout=HTTP_TIMEOUT,
        )
        assert detail["id"] == "29705518"
        assert detail["team"] is None
        assert detail["team_slug"] == TEAM_SLUG
        assert detail["date"] == "2026-06-20T10:00:00"
        assert detail["location"] == "Sjöängsskolan"
        assert detail["assembly_time"] == "09:30"
        assert detail["notes"] == "Ta med vatten\noch boll"
        assert detail["responses"] == []
        assert detail["rsvp"] == {
            "yes": None,
            "no": None,
            "unanswered": None,
            "my_response": "yes",
            "url": f"https://www.laget.se/{TEAM_SLUG}/Rsvp/29705518/{USER_ID}",
        }

    def test_user_rsvp_none_and_disabled_returns_none(self):
        raw = api_event(10, "2026-06-20T08:00:00", rsvp=False, userRsvp=None)
        session = session_with({"event": raw})
        assert fetch_event_detail(session, TEAM_SLUG, "10")["rsvp"] is None

    def test_requires_verified_detail_envelope(self):
        session = session_with({"events": []})
        with pytest.raises(ParseError, match="missing event"):
            fetch_event_detail(session, TEAM_SLUG, "10")


class TestSubmitRsvp:
    def test_yes_preserves_current_fields_and_puts_comment_in_answer(self):
        session = session_with({"event": api_event(10, "2026-06-20T08:00:00")})
        detail = fetch_event_detail(session, TEAM_SLUG, "10")
        put_response = MagicMock()
        session.put.return_value = put_response

        result = submit_rsvp(
            session,
            detail["rsvp"]["url"],
            "yes",
            comment="Kommer senare",
            event_id="10",
        )

        assert result is put_response
        session.put.assert_called_once_with(
            f"{API_BASE_URL}/v1/events/10/rsvp/{USER_ID}",
            json={
                "siteId": int(SITE_ID),
                "attending": 1,
                "car": 2,
                "assembly": True,
                "answer": "Kommer senare",
                "reason": "",
            },
            timeout=HTTP_TIMEOUT,
        )
        put_response.raise_for_status.assert_called_once_with()

    def test_no_maps_comment_to_reason_and_keeps_answer(self):
        session = session_with({"event": api_event(10, "2026-06-20T08:00:00")})
        detail = fetch_event_detail(session, TEAM_SLUG, "10")
        submit_rsvp(session, detail["rsvp"]["url"], "no", comment="Sjuk", event_id="10")
        payload = session.put.call_args.kwargs["json"]
        assert payload["attending"] == 2
        assert payload["answer"] == "Tidigare svar"
        assert payload["reason"] == "Sjuk"

    def test_requires_cached_detail_for_site_id(self):
        session = session_with()
        with pytest.raises(ParseError, match="RSVP site"):
            submit_rsvp(session, f"https://www.laget.se/x/Rsvp/10/{USER_ID}", "yes")

    def test_rejects_invalid_response(self):
        with pytest.raises(ValueError):
            submit_rsvp(session_with(), "ignored", "maybe")


def test_runtime_module_contains_no_html_endpoint_or_parser_symbols():
    import laget_cli.api.calendar as calendar

    source = open(calendar.__file__, encoding="utf-8").read()
    assert "Event/Single" not in source
    assert "FilterEvents" not in source
    assert "HTMLParser" not in source

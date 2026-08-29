"""Focused edge-case tests for JSON event detail and RSVP writes."""

from unittest.mock import MagicMock

import pytest

from laget_cli.api.calendar import API_BASE_URL, fetch_event_detail, submit_rsvp
from laget_cli.errors import ParseError
from laget_cli.session import HTTP_TIMEOUT


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def _event(**overrides):
    event = {
        "id": 10,
        "site": {"id": 44, "url": "https://www.laget.se/Club-Team"},
        "dateStart": 1781510400000,
        "dateEnd": 1781514000000,
        "title": "Match",
        "eventType": 4,
        "place": {"name": "Plan A", "mapUrl": "https://maps.example/plan-a"},
        "assembly": {"date": 1781508600000, "enabled": True, "info": "Vid entrén"},
        "isCancelled": True,
        "rsvp": True,
        "userRsvp": {
            "attending": 2,
            "attendingAssembly": False,
            "numCarSeats": 0,
            "answer": "Gammalt svar",
            "reason": "Gammal orsak",
        },
    }
    event.update(overrides)
    return event


def _session(payload=None):
    session = MagicMock()
    session.user_id = "77"
    session.team_site_ids = {"Club-Team": "44"}
    if payload is not None:
        session.get.return_value = _response(payload)
    return session


def test_detail_accepts_explicit_site_id_and_object_location():
    session = _session({"event": _event()})

    detail = fetch_event_detail(session, "Club-Team", "10", site_id=44)

    assert detail["cancelled"] is True
    assert detail["location"] == "Plan A"
    assert detail["location_url"] == "https://maps.example/plan-a"
    assert detail["assembly_time"] == "09:30"
    assert detail["rsvp"]["my_response"] == "no"
    session.get.assert_called_once_with(
        f"{API_BASE_URL}/v4/events/10",
        params={"siteId": "44"},
        timeout=HTTP_TIMEOUT,
    )


def test_submit_without_comment_preserves_existing_answer_and_reason():
    session = _session({"event": _event()})
    detail = fetch_event_detail(session, "Club-Team", "10")

    submit_rsvp(session, detail["rsvp"]["url"], "yes", event_id="10")

    assert session.put.call_args.kwargs["json"] == {
        "siteId": 44,
        "attending": 1,
        "car": 0,
        "assembly": False,
        "answer": "Gammalt svar",
        "reason": "Gammal orsak",
    }


def test_event_calls_require_session_identity():
    session = _session()
    session.user_id = None

    with pytest.raises(ParseError, match="user_id"):
        submit_rsvp(session, "https://www.laget.se/Club-Team/Rsvp/10/77", "yes")


def test_detail_requires_known_site_mapping():
    session = _session({"event": _event()})
    session.team_site_ids = {}

    with pytest.raises(ParseError, match="No site id"):
        fetch_event_detail(session, "Unknown-Team", "10")


def test_concernees_are_normalized_and_single_child_is_default_target():
    event = _event(
        userRsvp=None,
        concernees=[{
            "id": 88,
            "name": "Barnet",
            "rsvp": {"attending": 2, "answer": "", "reason": "Sjuk"},
        }],
    )
    session = _session({"event": event})
    detail = fetch_event_detail(session, "Club-Team", "10")

    assert detail["responses"] == [{
        "id": "88",
        "name": "Barnet",
        "my_response": "no",
        "answer": "",
        "reason": "Sjuk",
    }]
    assert detail["rsvp"]["url"].endswith("/Rsvp/10/88")
    submit_rsvp(session, detail["rsvp"]["url"], "yes", event_id="10")
    assert session.put.call_args.args[0].endswith("/v1/events/10/rsvp/88")


def test_multiple_concernees_require_explicit_eligible_member():
    event = _event(
        userRsvp=None,
        concernees=[
            {"id": 88, "name": "Barn A", "rsvp": {"attending": 0}},
            {"id": 99, "name": "Barn B", "rsvp": {"attending": 1}},
        ],
    )
    session = _session({"event": event})
    fetch_event_detail(session, "Club-Team", "10")

    with pytest.raises(ParseError, match="member_id is required"):
        submit_rsvp(session, "https://www.laget.se/Club-Team/Rsvp/10/77", "yes", event_id="10")

    submit_rsvp(
        session,
        "https://www.laget.se/Club-Team/Rsvp/10/77",
        "no",
        event_id="10",
        member_id="99",
    )
    assert session.put.call_args.args[0].endswith("/v1/events/10/rsvp/99")


def test_explicit_ineligible_member_is_rejected():
    event = _event(
        userRsvp=None,
        concernees=[{"id": 88, "name": "Barnet", "rsvp": {"attending": 0}}],
    )
    session = _session({"event": event})
    fetch_event_detail(session, "Club-Team", "10")

    with pytest.raises(ParseError, match="not eligible"):
        submit_rsvp(
            session,
            "https://www.laget.se/Club-Team/Rsvp/10/88",
            "yes",
            event_id="10",
            member_id="999",
        )


def test_authenticated_user_wins_when_multiple_members_are_eligible():
    event = _event(
        concernees=[
            {"id": 77, "name": "Vuxen", "rsvp": {"attending": 1, "numCarSeats": 1}},
            {"id": 88, "name": "Barnet", "rsvp": {"attending": 0}},
        ],
    )
    session = _session({"event": event})
    detail = fetch_event_detail(session, "Club-Team", "10")

    submit_rsvp(session, detail["rsvp"]["url"], "yes", event_id="10")

    assert session.put.call_args.args[0].endswith("/v1/events/10/rsvp/77")


def test_single_concernee_wins_before_authenticated_user():
    event = _event(
        concernees=[{"id": 88, "name": "Barnet", "rsvp": {"attending": 0}}],
    )
    session = _session({"event": event})
    detail = fetch_event_detail(session, "Club-Team", "10")

    assert detail["rsvp"]["url"].endswith("/Rsvp/10/88")
    submit_rsvp(session, detail["rsvp"]["url"], "yes", event_id="10")
    assert session.put.call_args.args[0].endswith("/v1/events/10/rsvp/88")

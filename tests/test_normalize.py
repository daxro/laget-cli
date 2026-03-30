import sys
from datetime import datetime
from unittest.mock import patch

import pytest

from laget_cli.api.normalize import (
    _infer_notification_type,
    _normalize_datetime,
    _normalize_event_type,
    _normalize_time,
    _strip_html,
)

FIXED_NOW = datetime(2024, 6, 15, 14, 30, 0)


class TestNormalizeDatetime:
    def test_full_date_swedish(self):
        assert _normalize_datetime("28 aug 2023") == "2023-08-28T00:00:00"

    def test_full_date_all_months(self):
        cases = [
            ("1 jan 2024", "2024-01-01T00:00:00"),
            ("15 feb 2024", "2024-02-15T00:00:00"),
            ("3 mar 2024", "2024-03-03T00:00:00"),
            ("10 apr 2024", "2024-04-10T00:00:00"),
            ("20 maj 2024", "2024-05-20T00:00:00"),
            ("5 jun 2024", "2024-06-05T00:00:00"),
            ("7 jul 2024", "2024-07-07T00:00:00"),
            ("22 sep 2024", "2024-09-22T00:00:00"),
            ("11 okt 2024", "2024-10-11T00:00:00"),
            ("30 nov 2024", "2024-11-30T00:00:00"),
            ("25 dec 2024", "2024-12-25T00:00:00"),
        ]
        for raw, expected in cases:
            assert _normalize_datetime(raw) == expected

    def test_full_month_names(self):
        cases = [
            ("15 januari 2024", "2024-01-15T00:00:00"),
            ("28 februari 2024", "2024-02-28T00:00:00"),
            ("1 mars 2024", "2024-03-01T00:00:00"),
            ("10 april 2024", "2024-04-10T00:00:00"),
            ("5 juni 2024", "2024-06-05T00:00:00"),
            ("7 juli 2024", "2024-07-07T00:00:00"),
            ("22 augusti 2024", "2024-08-22T00:00:00"),
            ("3 september 2024", "2024-09-03T00:00:00"),
            ("11 oktober 2024", "2024-10-11T00:00:00"),
            ("30 november 2024", "2024-11-30T00:00:00"),
            ("25 december 2024", "2024-12-25T00:00:00"),
        ]
        for raw, expected in cases:
            assert _normalize_datetime(raw) == expected, f"Failed for {raw}"

    def test_date_no_year_current_year(self):
        # June 10 with fixed now of June 15 2024 -> same year
        with patch("laget_cli.api.normalize.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _normalize_datetime("10 jun")
        assert result == "2024-06-10T00:00:00"

    def test_date_no_year_far_future_uses_previous_year(self):
        # Dec 25 with fixed now of June 15 2024 -> Dec is >6mo ahead, use 2023
        with patch("laget_cli.api.normalize.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _normalize_datetime("25 dec")
        assert result == "2023-12-25T00:00:00"

    def test_idag(self):
        with patch("laget_cli.api.normalize.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _normalize_datetime("idag")
        assert result == "2024-06-15T00:00:00"

    def test_igar(self):
        with patch("laget_cli.api.normalize.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _normalize_datetime("igår")
        assert result == "2024-06-14T00:00:00"

    def test_timmar_sedan(self):
        with patch("laget_cli.api.normalize.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _normalize_datetime("2 timmar sedan")
        assert result == "2024-06-15T12:30:00"

    def test_minuter_sedan(self):
        with patch("laget_cli.api.normalize.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _normalize_datetime("45 minuter sedan")
        assert result == "2024-06-15T13:45:00"

    def test_iso_date_passthrough(self):
        assert _normalize_datetime("2024-03-15") == "2024-03-15T00:00:00"

    def test_iso_datetime_passthrough(self):
        assert _normalize_datetime("2024-03-15T10:30:00") == "2024-03-15T10:30:00"

    def test_none_returns_none(self):
        assert _normalize_datetime(None) is None

    def test_invalid_returns_none(self, capsys):
        result = _normalize_datetime("not a date")
        assert result is None
        assert "Warning" in capsys.readouterr().err


class TestNormalizeTime:
    def test_extracts_time(self):
        assert _normalize_time("10:00") == "10:00"
        assert _normalize_time("11:15") == "11:15"
        assert _normalize_time("9:05") == "9:05"

    def test_extracts_from_text(self):
        assert _normalize_time("Samlingstid: 09:30") == "09:30"

    def test_none_returns_none(self):
        assert _normalize_time(None) is None

    def test_no_time_in_string_returns_none(self):
        assert _normalize_time("no time here") is None


class TestNormalizeEventType:
    def test_traning(self):
        assert _normalize_event_type("träning") == "training"
        assert _normalize_event_type("traning") == "training"

    def test_traningsmatch(self):
        assert _normalize_event_type("träningsmatch") == "match"
        assert _normalize_event_type("traningsmatch") == "match"

    def test_match(self):
        assert _normalize_event_type("match") == "match"

    def test_cup(self):
        assert _normalize_event_type("cup") == "match"

    def test_tavling(self):
        assert _normalize_event_type("tävling") == "match"
        assert _normalize_event_type("tavling") == "match"

    def test_mote(self):
        assert _normalize_event_type("möte") == "meeting"
        assert _normalize_event_type("mote") == "meeting"

    def test_aktivitet(self):
        assert _normalize_event_type("aktivitet") == "other"

    def test_prefix_match(self):
        assert _normalize_event_type("träningsmatch mot Boo IF") == "match"
        assert _normalize_event_type("träning med extra övningar") == "training"

    def test_unknown_returns_other(self):
        assert _normalize_event_type("fest") == "other"
        assert _normalize_event_type("") == "other"

    def test_none_returns_other(self):
        assert _normalize_event_type(None) == "other"

    def test_case_insensitive(self):
        assert _normalize_event_type("TRÄNING") == "training"
        assert _normalize_event_type("Match") == "match"


class TestStripHtml:
    def test_strips_br_tags(self):
        assert _strip_html("line1<br>line2") == "line1\nline2"
        assert _strip_html("line1<br/>line2") == "line1\nline2"
        assert _strip_html("line1<br />line2") == "line1\nline2"

    def test_strips_closing_block_tags(self):
        assert _strip_html("<p>text</p>") == "text"
        assert _strip_html("<div>text</div>") == "text"

    def test_strips_remaining_tags(self):
        assert _strip_html("<b>bold</b> text") == "bold text"
        assert _strip_html('<img src="emoji.png" alt="smile">') == ""

    def test_collapses_excessive_newlines(self):
        result = _strip_html("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_strips_whitespace(self):
        assert _strip_html("  text  ") == "text"

    def test_complex_html(self):
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        result = _strip_html(html)
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_none_returns_empty_string(self):
        assert _strip_html(None) == ""


class TestInferNotificationType:
    def test_news_url(self):
        assert _infer_notification_type("/TeamSlug/News/9876") == "news"

    def test_guestbook_url(self):
        assert _infer_notification_type("/TeamSlug/Guestbook") == "guestbook"

    def test_event_url(self):
        assert _infer_notification_type("/TeamSlug/Event/12345") == "rsvp"

    def test_unknown_url_returns_unknown_and_warns(self, capsys):
        result = _infer_notification_type("/TeamSlug/SomethingElse")
        assert result == "unknown"
        assert "Warning" in capsys.readouterr().err

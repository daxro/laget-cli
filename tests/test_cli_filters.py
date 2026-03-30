import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from laget_cli.cli import (
    _filter_by_team,
    _filter_items_since,
    _filter_items_until,
    _resolve_since,
    _resolve_until,
    _validate_date_flag,
)


class TestValidateDateFlag:
    def test_valid_date_passes_through(self):
        assert _validate_date_flag("2024-03-15", "--since") == "2024-03-15"

    def test_none_returns_none(self):
        assert _validate_date_flag(None, "--since") is None

    def test_all_returns_none(self):
        assert _validate_date_flag("all", "--since") is None
        assert _validate_date_flag("ALL", "--since") is None
        assert _validate_date_flag("All", "--since") is None

    def test_invalid_format_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _validate_date_flag("15-03-2024", "--since")
        assert exc.value.code == 2

    def test_invalid_format_exits_with_error_json(self, capsys):
        with pytest.raises(SystemExit):
            _validate_date_flag("not-a-date", "--since")
        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "invalid_input"
        assert "--since" in err["message"]


class TestResolveSince:
    def test_explicit_cli_value_wins(self):
        result = _resolve_since("2024-01-01", {})
        assert result == "2024-01-01"

    def test_explicit_all_returns_none(self):
        result = _resolve_since("all", {"DEFAULT_SINCE_DAYS": "7"})
        assert result is None

    def test_default_since_days_from_config(self):
        config = {"DEFAULT_SINCE_DAYS": "7"}
        expected = (date.today() - timedelta(days=7)).isoformat()
        assert _resolve_since(None, config) == expected

    def test_default_30_days_when_no_config(self):
        expected = (date.today() - timedelta(days=30)).isoformat()
        assert _resolve_since(None, {}) == expected

    def test_invalid_default_since_days_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _resolve_since(None, {"DEFAULT_SINCE_DAYS": "abc"})
        assert exc.value.code == 2

    def test_negative_default_since_days_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _resolve_since(None, {"DEFAULT_SINCE_DAYS": "-5"})
        assert exc.value.code == 2

    def test_zero_default_since_days_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _resolve_since(None, {"DEFAULT_SINCE_DAYS": "0"})
        assert exc.value.code == 2


class TestResolveUntil:
    def test_explicit_value_validates_and_returns(self):
        assert _resolve_until("2024-12-31") == "2024-12-31"

    def test_none_returns_none(self):
        assert _resolve_until(None) is None

    def test_all_returns_none(self):
        assert _resolve_until("all") is None

    def test_invalid_format_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _resolve_until("31/12/2024")
        assert exc.value.code == 2


class TestFilterItemsSince:
    ITEMS = [
        {"date": "2024-01-01T00:00:00", "team_slug": "TeamA"},
        {"date": "2024-03-15T00:00:00", "team_slug": "TeamA"},
        {"date": "2024-06-01T00:00:00", "team_slug": "TeamB"},
    ]

    def test_filters_items_on_or_after_since(self):
        result = _filter_items_since(self.ITEMS, "2024-03-15")
        assert len(result) == 2
        assert result[0]["date"] == "2024-03-15T00:00:00"

    def test_none_returns_all(self):
        result = _filter_items_since(self.ITEMS, None)
        assert len(result) == 3

    def test_boundary_inclusive(self):
        result = _filter_items_since(self.ITEMS, "2024-01-01")
        assert len(result) == 3

    def test_no_items_after_since(self):
        result = _filter_items_since(self.ITEMS, "2025-01-01")
        assert result == []

    def test_custom_date_key(self):
        items = [{"start": "2024-03-01", "team_slug": "A"}, {"start": "2024-05-01", "team_slug": "B"}]
        result = _filter_items_since(items, "2024-04-01", date_key="start")
        assert len(result) == 1
        assert result[0]["start"] == "2024-05-01"


class TestFilterItemsUntil:
    ITEMS = [
        {"date": "2024-01-01T00:00:00", "team_slug": "TeamA"},
        {"date": "2024-03-15T00:00:00", "team_slug": "TeamA"},
        {"date": "2024-06-01T00:00:00", "team_slug": "TeamB"},
    ]

    def test_filters_items_on_or_before_until(self):
        result = _filter_items_until(self.ITEMS, "2024-03-15")
        assert len(result) == 2

    def test_none_returns_all(self):
        result = _filter_items_until(self.ITEMS, None)
        assert len(result) == 3

    def test_boundary_inclusive(self):
        result = _filter_items_until(self.ITEMS, "2024-06-01")
        assert len(result) == 3

    def test_no_items_before_until(self):
        result = _filter_items_until(self.ITEMS, "2023-12-31")
        assert result == []

    def test_uses_date_part_only(self):
        # Ensures time component does not affect comparison
        items = [{"date": "2024-03-15T23:59:59", "team_slug": "A"}]
        result = _filter_items_until(items, "2024-03-15")
        assert len(result) == 1


class TestFilterByTeam:
    ITEMS = [
        {"team_slug": "TeamAlpha-P2021", "date": "2024-01-01T00:00:00"},
        {"team_slug": "TeamBeta-F2019", "date": "2024-01-02T00:00:00"},
        {"team_slug": "TeamAlpha-P2019", "date": "2024-01-03T00:00:00"},
    ]

    def test_exact_slug_match(self):
        result = _filter_by_team(self.ITEMS, "TeamAlpha-P2021")
        assert len(result) == 1

    def test_substring_match(self):
        result = _filter_by_team(self.ITEMS, "TeamAlpha")
        assert len(result) == 2

    def test_case_insensitive(self):
        result = _filter_by_team(self.ITEMS, "teamalpha")
        assert len(result) == 2

    def test_none_returns_all(self):
        result = _filter_by_team(self.ITEMS, None)
        assert len(result) == 3

    def test_no_match_returns_empty(self):
        result = _filter_by_team(self.ITEMS, "nonexistent")
        assert result == []

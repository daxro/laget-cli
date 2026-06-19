import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from laget_cli.cli import _mask_email, _progress, _use_color, main, print_logo
from laget_cli.errors import AuthError


class TestMaskEmail:
    def test_masks_normal_email(self):
        assert _mask_email("user@example.com") == "use****@example.com"

    def test_masks_short_local(self):
        assert _mask_email("ab@test.com") == "a****@test.com"

    def test_returns_none_for_none(self):
        assert _mask_email(None) is None

    def test_returns_empty_for_empty(self):
        assert _mask_email("") == ""

    def test_no_at_sign_returns_as_is(self):
        assert _mask_email("noemail") == "noemail"


class TestProgress:
    def test_prints_to_stderr(self, capsys):
        _progress("hello")
        assert capsys.readouterr().err == "hello\n"

    def test_quiet_suppresses(self, capsys):
        _progress("hello", quiet=True)
        assert capsys.readouterr().err == ""


class TestMainVersion:
    def test_version(self, capsys):
        from importlib.metadata import version
        expected = version("laget-cli")
        with patch("sys.argv", ["laget", "--version"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            assert expected in capsys.readouterr().out


class TestMainNoCommand:
    def test_no_command_shows_help_and_exits_zero(self, capsys):
        with patch("sys.argv", ["laget"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0




class TestFieldsFlag:
    def test_notifications_fields_filters_output(self):
        from io import StringIO

        notifications = [
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": "T1", "team_slug": "A", "url": "/x/News/1"},
        ]
        teams = [{"team_slug": "A", "name": "A", "club": "C"}]

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams), \
             patch("laget_cli.cli.fetch_notifications", return_value=notifications), \
             patch("laget_cli.cli.resolve_team_names", side_effect=lambda n, t: n), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget", "-q", "notifications", "--since", "all", "--fields", "date,type"]):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()

        result = json.loads(out.getvalue())
        assert len(result) == 1
        assert set(result[0].keys()) == {"date", "type"}


class TestCalendarCommand:
    def _run_calendar(self, argv, events_by_slug, teams_data=None):
        from io import StringIO
        if teams_data is None:
            teams_data = [
                {"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "FK"},
                {"team_slug": "TeamAlpha-P2019", "name": "P2019", "club": "FK"},
            ]

        def fetch_calendar_range(_session, team_slug, _since, _until, limit=None):
            events = events_by_slug.get(team_slug, [])
            return events[:limit] if limit is not None else events

        with patch("laget_cli.cli._get_session") as mock_session, \
             patch("laget_cli.cli.fetch_teams", return_value=teams_data), \
             patch("laget_cli.cli.filter_teams_by_club", return_value=teams_data), \
             patch("laget_cli.cli.fetch_calendar_range", side_effect=fetch_calendar_range), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "x@x.com", "PASSWORD": "pw"}):
            mock_session.return_value = MagicMock()
            with patch("sys.argv", ["laget", "-q"] + argv):
                out = StringIO()
                with patch("sys.stdout", out):
                    main()
                return json.loads(out.getvalue())

    def test_calendar_preserves_team_envelope_when_events_are_empty(self):
        result = self._run_calendar(
            ["calendar", "--team", "P2021", "--since", "2026-06-01", "--until", "2026-06-30"],
            {"TeamAlpha-P2021": []},
        )

        assert result == [
            {"team": "P2021", "team_slug": "TeamAlpha-P2021", "events": []},
        ]


class TestNotificationsLimit:
    def _run_notifications(self, argv, notifications_data, teams_data=None):
        from io import StringIO
        if teams_data is None:
            teams_data = [{"team_slug": "TeamAlpha-P2021", "name": "P2021", "club": "FK"}]

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

    def test_limit_truncates_results(self):
        notifications = [
            {"date": f"2026-03-{i:02d}T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"}
            for i in range(1, 11)
        ]
        result = self._run_notifications(["notifications", "--since", "all", "--limit", "3"], notifications)
        assert len(result) == 3

    def test_no_limit_returns_all(self):
        notifications = [
            {"date": f"2026-03-{i:02d}T00:00:00", "type": "news", "author": "A",
             "title": "t", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"}
            for i in range(1, 6)
        ]
        result = self._run_notifications(["notifications", "--since", "all"], notifications)
        assert len(result) == 5

    def test_limit_applied_after_sort(self):
        notifications = [
            {"date": "2026-03-01T00:00:00", "type": "news", "author": "A",
             "title": "old", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/1"},
            {"date": "2026-03-29T00:00:00", "type": "news", "author": "B",
             "title": "new", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/2"},
            {"date": "2026-03-15T00:00:00", "type": "news", "author": "C",
             "title": "mid", "team": None, "team_slug": "TeamAlpha-P2021", "url": "/x/News/3"},
        ]
        result = self._run_notifications(["notifications", "--since", "all", "--limit", "2"], notifications)
        assert len(result) == 2
        # Should be the 2 newest (sorted desc)
        assert result[0]["date"] == "2026-03-29T00:00:00"
        assert result[1]["date"] == "2026-03-15T00:00:00"


class TestStatusCommand:
    @patch("laget_cli.cli._sync_state", return_value={"child_teams": {}})
    @patch("laget_cli.cli.fetch_children")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_status_json_outputs_json(self, mock_dotenv, mock_login, mock_fetch_teams, mock_fetch_children, mock_sync, capsys):
        mock_dotenv.return_value = {"EMAIL": "user@example.com", "PASSWORD": "pass", "CLUB": "Test FK"}
        mock_login.return_value = MagicMock()
        mock_fetch_teams.return_value = [{"name": "T1", "club": "Test FK", "team_slug": "a"}]
        mock_fetch_children.return_value = [{"name": "Alice", "id": "123"}]

        with patch("sys.argv", ["laget", "-q", "status", "--json"]):
            main()

        output = json.loads(capsys.readouterr().out)
        assert output["configured"] is True
        assert output["email"] == "use****@example.com"
        assert output["session"] == "valid"
        assert len(output["teams"]) == 1
        assert len(output["children"]) == 1

    @patch("laget_cli.cli._sync_state", return_value={"child_teams": {}})
    @patch("laget_cli.cli.fetch_children")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_status_human_readable(self, mock_dotenv, mock_login, mock_fetch_teams, mock_fetch_children, mock_sync, capsys):
        mock_dotenv.return_value = {"EMAIL": "user@example.com", "PASSWORD": "pass", "CLUB": "Test FK"}
        mock_login.return_value = MagicMock()
        mock_fetch_teams.return_value = [{"name": "T1", "club": "Test FK", "team_slug": "a"}]
        mock_fetch_children.return_value = [{"name": "Alice", "id": "123"}]

        with patch("sys.argv", ["laget", "-q", "status"]):
            main()

        out = capsys.readouterr().out
        assert "Email: use****@example.com" in out
        assert "Session: valid" in out
        assert "T1 (Test FK)" in out
        assert "Alice" in out

    @patch("laget_cli.cli.dotenv_values")
    def test_status_not_configured_outputs_json(self, mock_dotenv, capsys):
        mock_dotenv.return_value = {}

        with patch("sys.argv", ["laget", "-q", "status", "--json"]):
            with pytest.raises(SystemExit, match="2"):
                main()

        output = json.loads(capsys.readouterr().out)
        assert output["configured"] is False

    @patch("laget_cli.cli.dotenv_values")
    def test_status_not_configured_human_shows_message(self, mock_dotenv, capsys):
        mock_dotenv.return_value = {}

        with patch("sys.argv", ["laget", "-q", "status"]):
            with pytest.raises(SystemExit, match="2"):
                main()

        out = capsys.readouterr().out
        assert "Not configured" in out


class TestNewsCommand:
    @patch("laget_cli.cli.fetch_article")
    @patch("laget_cli.cli.filter_teams_by_club")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_news_outputs_article_json(self, mock_dotenv, mock_login, mock_fetch_teams, mock_filter, mock_fetch_article, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.return_value = MagicMock()
        mock_filter.return_value = [{"team_slug": "TeamA-P2021", "name": "P2021", "club": "Team A"}]
        mock_fetch_teams.return_value = mock_filter.return_value
        mock_fetch_article.return_value = {
            "id": "123",
            "title": "Test Article",
            "author": "Author",
            "date": "2026-03-28T00:00:00",
            "body": "Article body",
            "view_count": 10,
            "comments": [],
            "team": None,
            "team_slug": None,
        }

        with patch("sys.argv", ["laget", "-q", "news", "--team", "TeamA-P2021", "123"]):
            main()

        output = json.loads(capsys.readouterr().out)
        assert output["id"] == "123"
        assert output["team"] == "P2021"
        assert output["team_slug"] == "TeamA-P2021"

    @patch("laget_cli.cli.filter_teams_by_club")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_news_unknown_team_emits_error(self, mock_dotenv, mock_login, mock_fetch_teams, mock_filter, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.return_value = MagicMock()
        mock_filter.return_value = [{"team_slug": "TeamA-P2021", "name": "P2021", "club": "A"}]
        mock_fetch_teams.return_value = mock_filter.return_value

        with patch("sys.argv", ["laget", "-q", "news", "--team", "nonexistent", "123"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 4



class TestPrintLogo:
    def test_use_color_true_on_tty(self):
        mock_stderr = MagicMock()
        mock_stderr.isatty.return_value = True
        env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "TERM")}
        with patch("sys.stderr", mock_stderr):
            with patch.dict("os.environ", env, clear=True):
                result = _use_color()
        assert result is True

    def test_logo_has_ansi_on_tty(self):
        import io
        buf = io.StringIO()
        mock_stderr = MagicMock()
        mock_stderr.isatty.return_value = True
        mock_stderr.write = buf.write
        mock_stderr.flush = buf.flush
        env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "TERM")}
        with patch("sys.stderr", mock_stderr):
            with patch.dict("os.environ", env, clear=True):
                print_logo()
        assert "\033[" in buf.getvalue()

    def test_logo_no_ansi_when_no_color_set(self, capsys):
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            print_logo()
        err = capsys.readouterr().err
        assert "\033[" not in err
        assert "|___/" in err

    def test_logo_no_ansi_when_term_dumb(self, capsys):
        with patch.dict("os.environ", {"TERM": "dumb"}):
            print_logo()
        err = capsys.readouterr().err
        assert "\033[" not in err

    def test_logo_no_ansi_when_not_tty(self, capsys):
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = False
            mock_stderr.write = sys.stderr.write
            mock_stderr.flush = sys.stderr.flush
            print_logo()
        err = capsys.readouterr().err
        assert "\033[" not in err


class TestSetupCommand:
    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_interactive_setup_calls_print_logo(self, mock_dotenv, mock_logo):
        mock_dotenv.return_value = {"LAGET_EMAIL": "t@t.com", "LAGET_PASSWORD": "pw"}
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        with patch("sys.argv", ["laget", "setup"]):
            with patch("sys.stdin", mock_stdin), \
                 patch("builtins.input", return_value="n"), \
                 patch("laget_cli.cli.login"):
                main()

        mock_logo.assert_called_once_with()

    @patch("laget_cli.cli._print_status")
    @patch("laget_cli.cli._get_status", return_value={})
    @patch("laget_cli.cli._persist_setup")
    @patch("laget_cli.cli.fetch_teams")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_interactive_default_clears_existing_club_filter(
        self,
        mock_dotenv,
        mock_logo,
        mock_login,
        mock_teams,
        mock_persist,
        _mock_status,
        _mock_print,
    ):
        from laget_cli.cli import _setup

        mock_dotenv.return_value = {
            "LAGET_EMAIL": "old@example.com",
            "LAGET_PASSWORD": "old",
            "CLUB": "Old Club",
        }
        mock_login.return_value = MagicMock()
        mock_teams.return_value = [
            {"name": "A", "club": "Club A", "team_slug": "club-a"},
            {"name": "B", "club": "Club B", "team_slug": "club-b"},
        ]
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        with patch("sys.stdin", mock_stdin), \
             patch("builtins.input", side_effect=["y", "new@example.com", ""]), \
             patch("laget_cli.cli.getpass.getpass", return_value="new"):
            args = MagicMock(no_input=False, quiet=True, fields=None)
            _setup(args)

        mock_persist.assert_called_once_with(
            "new@example.com",
            "new",
            None,
            mock_login.return_value,
            reset_state=True,
        )
        mock_logo.assert_called_once_with()


class TestSignalHandling:
    def test_keyboard_interrupt_exits_130(self):
        with patch("sys.argv", ["laget", "notifications"]):
            with patch("laget_cli.cli._notifications", side_effect=KeyboardInterrupt):
                with patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
                    with pytest.raises(SystemExit) as exc:
                        main()
                    assert exc.value.code == 130

    def test_keyboard_interrupt_no_traceback(self, capsys):
        with patch("sys.argv", ["laget", "notifications"]):
            with patch("laget_cli.cli._notifications", side_effect=KeyboardInterrupt):
                with patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"}):
                    with pytest.raises(SystemExit):
                        main()
        err = capsys.readouterr().err
        assert "Traceback" not in err

    def test_keyboard_interrupt_emits_structured_error(self, capsys):
        with patch("sys.argv", ["laget", "notifications"]):
            with patch("laget_cli.cli._notifications", side_effect=KeyboardInterrupt):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 130
        assert json.loads(capsys.readouterr().err)["error"] == "interrupted"


class TestSetupNoInput:
    @patch("laget_cli.cli._get_status")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli._persist_setup")
    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_no_input_flag_skips_prompts(self, mock_dotenv, mock_logo, mock_persist, mock_login, mock_status, capsys):
        mock_dotenv.return_value = {}
        mock_login.return_value = MagicMock()
        mock_status.return_value = {"configured": True, "email": "t****@t.com", "session": "valid", "club_filter": None, "teams": [], "children": [], "config_path": "/tmp/config.env", "session_path": "/tmp/session.json"}

        with patch.dict("os.environ", {"LAGET_EMAIL": "t@t.com", "LAGET_PASSWORD": "pw"}):
            with patch("sys.argv", ["laget", "-q", "setup", "--no-input"]):
                # stdin IS a tty, but --no-input should override
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = True
                    main()

        mock_persist.assert_called_once_with(
            "t@t.com", "pw", None, mock_login.return_value, reset_state=True
        )
        mock_login.assert_called_once_with("t@t.com", "pw", session_path=None)
        mock_logo.assert_not_called()

    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_no_input_flag_errors_without_env_vars(self, mock_dotenv, mock_logo, capsys):
        mock_dotenv.return_value = {}

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("LAGET_EMAIL", None)
            os.environ.pop("LAGET_PASSWORD", None)
            os.environ.pop("EMAIL", None)
            os.environ.pop("PASSWORD", None)
            with patch("sys.argv", ["laget", "setup", "--no-input"]):
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 2
        mock_logo.assert_not_called()
        assert json.loads(capsys.readouterr().err)["error"] == "setup_required"

    @patch("laget_cli.cli._get_status")
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli._persist_setup")
    @patch("laget_cli.cli.print_logo")
    @patch("laget_cli.cli.dotenv_values")
    def test_new_account_clears_existing_club_filter(
        self, mock_dotenv, mock_logo, mock_persist, mock_login, mock_status
    ):
        mock_dotenv.return_value = {
            "LAGET_EMAIL": "old@example.com",
            "LAGET_PASSWORD": "old",
            "CLUB": "Old Club",
        }
        mock_login.return_value = MagicMock()
        mock_status.return_value = {
            "configured": True,
            "email": "new****@example.com",
            "session": "valid",
            "club_filter": None,
            "teams": [],
            "children": [],
            "config_path": "/tmp/config.env",
            "session_path": "/tmp/session.json",
        }

        with patch.dict(
            "os.environ",
            {"LAGET_EMAIL": "new@example.com", "LAGET_PASSWORD": "new"},
        ), patch("sys.argv", ["laget", "setup", "--no-input", "-q"]):
            main()

        mock_persist.assert_called_once_with(
            "new@example.com",
            "new",
            None,
            mock_login.return_value,
            reset_state=True,
        )
        mock_logo.assert_not_called()


class TestGlobalFlagPosition:
    """Global flags (--debug, --no-input, -q) must work both before and after the subcommand."""

    @pytest.mark.parametrize("flag,attr,expected", [
        ("--debug", "debug", True),
        ("--no-input", "no_input", True),
        ("-q", "quiet", True),
    ])
    @pytest.mark.parametrize("position", ["before", "after"])
    def test_flag_propagates(self, flag, attr, expected, position, monkeypatch):
        import laget_cli.cli as cli_module

        argv_before = ["laget", flag, "notifications", "--since", "all"]
        argv_after = ["laget", "notifications", "--since", "all", flag]
        argv = argv_before if position == "before" else argv_after

        captured = {}
        monkeypatch.setattr(cli_module, "_configure_debug", lambda: None)
        monkeypatch.setattr(cli_module, "_notifications", lambda args: captured.update(args=args))
        monkeypatch.setattr(sys, "argv", argv)

        main()

        assert captured["args"].command == "notifications"
        assert getattr(captured["args"], attr) is expected


class TestGetStatusExceptionHandling:
    @patch("laget_cli.cli._load_state", return_value={})
    @patch("laget_cli.cli.fetch_children", side_effect=requests.ConnectionError("network down"))
    @patch("laget_cli.cli.fetch_teams", return_value=[{"name": "T1", "club": "C", "team_slug": "a"}])
    @patch("laget_cli.cli.filter_teams_by_club", return_value=[{"name": "T1", "club": "C", "team_slug": "a"}])
    @patch("laget_cli.cli.login", return_value=MagicMock())
    @patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"})
    def test_children_fetch_failure_warns_on_stderr(self, mock_dotenv, mock_login, mock_filter, mock_teams, mock_children, mock_state, capsys):
        from laget_cli.cli import _get_status
        status = _get_status()
        err = capsys.readouterr().err
        assert "Warning" in err or "warning" in err
        assert status["children"] == []

    @patch("laget_cli.cli.fetch_children", return_value=[])
    @patch("laget_cli.cli.fetch_teams", side_effect=requests.Timeout("timed out"))
    @patch("laget_cli.cli.filter_teams_by_club", return_value=[])
    @patch("laget_cli.cli.login", return_value=MagicMock())
    @patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "p"})
    def test_teams_fetch_failure_warns_on_stderr(self, mock_dotenv, mock_login, mock_filter, mock_teams, mock_children, capsys):
        from laget_cli.cli import _get_status
        status = _get_status()
        err = capsys.readouterr().err
        assert "Warning" in err or "warning" in err
        assert status["teams"] == []



class TestErrorHandling:
    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_auth_error_emits_json(self, mock_dotenv, mock_login, capsys):
        from laget_cli.errors import AuthError
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.side_effect = AuthError("bad credentials")

        with patch("sys.argv", ["laget", "-q", "notifications"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 3

        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "auth_failed"

    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_timeout_emits_json(self, mock_dotenv, mock_login, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.side_effect = requests.Timeout()

        with patch("sys.argv", ["laget", "-q", "notifications"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 5

        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "request_timeout"

    @patch("laget_cli.cli.login")
    @patch("laget_cli.cli.dotenv_values")
    def test_connection_error_emits_json(self, mock_dotenv, mock_login, capsys):
        mock_dotenv.return_value = {"EMAIL": "t@t.com", "PASSWORD": "p"}
        mock_login.side_effect = requests.ConnectionError()

        with patch("sys.argv", ["laget", "-q", "notifications"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 5

        err = json.loads(capsys.readouterr().err)
        assert err["error"] == "connection_failed"


class TestResetCommand:
    def test_reset_deletes_files(self, tmp_path, capsys):
        from laget_cli.cli import _reset

        config = tmp_path / "config.env"
        session = tmp_path / "session.json"
        state = tmp_path / "state.json"
        config.write_text("EMAIL=test@test.com\nPASSWORD=secret\n")
        session.write_text("{}")
        state.write_text("{}")

        args = MagicMock()
        args.quiet = False

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session), \
             patch("laget_cli.cli.STATE_FILE", state):
            _reset(args)

        assert not config.exists()
        assert not session.exists()
        assert not state.exists()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["reset"] is True
        assert len(data["deleted"]) == 3
        assert data["failed"] == []
        assert "Deleted" in captured.err

    def test_reset_already_clean(self, tmp_path, capsys):
        from laget_cli.cli import _reset

        config = tmp_path / "config.env"
        session = tmp_path / "session.json"
        state = tmp_path / "state.json"

        args = MagicMock()
        args.quiet = False

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session), \
             patch("laget_cli.cli.STATE_FILE", state):
            _reset(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["reset"] is True
        assert data["deleted"] == []
        assert data["failed"] == []
        assert "Nothing to reset" in captured.err

    def test_reset_quiet_suppresses_stderr(self, tmp_path, capsys):
        from laget_cli.cli import _reset

        config = tmp_path / "config.env"
        session = tmp_path / "session.json"
        state = tmp_path / "state.json"
        config.write_text("EMAIL=test@test.com\nPASSWORD=secret\n")

        args = MagicMock()
        args.quiet = True

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session), \
             patch("laget_cli.cli.STATE_FILE", state):
            _reset(args)

        captured = capsys.readouterr()
        assert captured.err == ""
        data = json.loads(captured.out)
        assert data["reset"] is True

    def test_reset_permission_error_exits_nonzero(self, tmp_path, capsys):
        from laget_cli.cli import _reset

        config = tmp_path / "config.env"
        session = tmp_path / "session.json"
        state = tmp_path / "state.json"
        config.write_text("EMAIL=test@test.com\nPASSWORD=secret\n")

        args = MagicMock()
        args.quiet = False

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session), \
             patch("laget_cli.cli.STATE_FILE", state), \
             patch.object(type(config), "unlink", side_effect=OSError("Permission denied")):
            with pytest.raises(SystemExit) as exc:
                _reset(args)
            assert exc.value.code == 1

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["failed"]) == 1
        assert "Failed to delete" in captured.err


class TestAgentSafetyContracts:
    def test_get_session_does_not_sync_state(self):
        from laget_cli.cli import _get_session

        with patch("laget_cli.cli.dotenv_values", return_value={"LAGET_EMAIL": "t@t.com", "LAGET_PASSWORD": "pw"}), \
             patch("laget_cli.cli.login", return_value=MagicMock()) as mock_login, \
             patch("laget_cli.cli.sync_child_team_mapping") as mock_sync:
            _get_session(quiet=True)

        mock_login.assert_called_once()
        mock_sync.assert_not_called()

    def test_status_fetches_once_and_syncs_explicitly(self):
        from laget_cli.cli import _get_status

        session = MagicMock()
        teams = [{"name": "P2021", "club": "Club", "team_slug": "Club-P2021"}]
        children = [{"name": "Alice", "id": "123"}]
        state = {"child_teams": {"123": {"team_slug": "Club-P2021", "team_name": "P2021"}}}
        config = {"LAGET_EMAIL": "t@t.com", "LAGET_PASSWORD": "pw"}

        with patch("laget_cli.cli.fetch_teams", return_value=teams) as mock_teams, \
             patch("laget_cli.cli.fetch_children", return_value=children) as mock_children, \
             patch("laget_cli.cli._sync_state", return_value=state) as mock_sync:
            status = _get_status(session=session, config=config)

        mock_teams.assert_called_once_with(session)
        mock_children.assert_called_once_with(session)
        mock_sync.assert_called_once_with(session, config, teams=teams, children=children, quiet=True)
        assert status["children"][0]["team_slug"] == "Club-P2021"

    def test_status_successful_empty_sync_does_not_load_stale_state(self):
        from laget_cli.cli import _get_status

        config = {"LAGET_EMAIL": "t@t.com", "LAGET_PASSWORD": "pw"}
        with patch("laget_cli.cli.fetch_teams", return_value=[]), \
             patch("laget_cli.cli.fetch_children", return_value=[]) as mock_children, \
             patch("laget_cli.cli._sync_state", return_value={"child_teams": {}}) as mock_sync, \
             patch("laget_cli.cli._load_state") as mock_load:
            status = _get_status(session=MagicMock(), config=config)

        mock_children.assert_called_once()
        mock_sync.assert_called_once()
        mock_load.assert_not_called()
        assert status["teams"] == []
        assert status["children"] == []

    def test_ambiguous_single_resource_team_exits_usage(self, capsys):
        from laget_cli.cli import _resolve_team_slug

        teams = [
            {"name": "A", "team_slug": "Club-A"},
            {"name": "B", "team_slug": "Club-B"},
        ]
        with pytest.raises(SystemExit) as exc:
            _resolve_team_slug("Club", teams)
        assert exc.value.code == 2
        assert json.loads(capsys.readouterr().err)["error"] == "ambiguous_team"

    def test_unknown_fields_fail_before_network(self, capsys):
        with patch("laget_cli.cli._get_session") as mock_session:
            with patch("sys.argv", ["laget", "notifications", "--fields", "bogus"]):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 2
        mock_session.assert_not_called()
        assert json.loads(capsys.readouterr().err)["error"] == "invalid_input"

    def test_setup_authenticates_before_persisting_and_redacts_password(self, capsys):
        secret = "do-not-print-this"
        with patch("laget_cli.cli.dotenv_values", return_value={}), \
             patch("laget_cli.cli.print_logo"), \
             patch("laget_cli.cli.login", side_effect=AuthError("Login failed")), \
             patch("laget_cli.cli._persist_setup") as mock_persist, \
             patch.dict("os.environ", {"LAGET_EMAIL": "t@t.com", "LAGET_PASSWORD": secret}):
            with patch("sys.argv", ["laget", "setup", "--no-input"]):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 3
        mock_persist.assert_not_called()
        captured = capsys.readouterr()
        assert secret not in captured.out
        assert secret not in captured.err

    def test_persist_setup_restores_previous_config_when_session_save_fails(self, tmp_path):
        from laget_cli.cli import _persist_setup

        config = tmp_path / "config.env"
        session_path = tmp_path / "session.json"
        original = 'LAGET_EMAIL="old@example.com"\nLAGET_PASSWORD="old"\n'
        config.write_text(original)

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session_path), \
             patch("laget_cli.cli.save_session", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                _persist_setup("new@example.com", "new", None, MagicMock())

        assert config.read_text() == original
        assert not session_path.exists()

    def test_persist_setup_restores_previous_session_when_save_fails_after_replace(self, tmp_path):
        from laget_cli.cli import _persist_setup

        config = tmp_path / "config.env"
        session_path = tmp_path / "session.json"
        original_config = 'LAGET_EMAIL="old@example.com"\nLAGET_PASSWORD="old"\n'
        original_session = '[{"name": "old"}]'
        config.write_text(original_config)
        session_path.write_text(original_session)

        def replace_then_fail(_session, path):
            path.write_text('[{"name": "new"}]')
            raise OSError("disk full")

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session_path), \
             patch("laget_cli.cli.save_session", side_effect=replace_then_fail):
            with pytest.raises(OSError):
                _persist_setup("new@example.com", "new", None, MagicMock())

        assert config.read_text() == original_config
        assert session_path.read_text() == original_session
        assert config.stat().st_mode & 0o777 == 0o600
        assert session_path.stat().st_mode & 0o777 == 0o600

    def test_account_switch_invalidates_previous_state_before_failed_sync(self, tmp_path):
        from laget_cli.cli import _get_status, _persist_setup

        config = tmp_path / "config.env"
        session_path = tmp_path / "session.json"
        state = tmp_path / "state.json"
        state.write_text(
            json.dumps({
                "child_teams": {
                    "123": {"team_slug": "Old-Club", "team_name": "Old Club"}
                }
            })
        )

        with patch("laget_cli.cli.CONFIG_FILE", config), \
             patch("laget_cli.cli.SESSION_FILE", session_path), \
             patch("laget_cli.cli.STATE_FILE", state), \
             patch("laget_cli.cli.save_session"):
            _persist_setup(
                "new@example.com",
                "new",
                None,
                MagicMock(),
                reset_state=True,
            )
            with patch("laget_cli.cli.fetch_teams", side_effect=requests.ConnectionError()), \
                 patch("laget_cli.cli.fetch_children", side_effect=requests.ConnectionError()):
                status = _get_status(
                    session=MagicMock(),
                    config={"LAGET_EMAIL": "new@example.com", "LAGET_PASSWORD": "new"},
                )

        assert json.loads(state.read_text()) == {"child_teams": {}}
        assert status["teams"] == []
        assert status["children"] == []
        assert state.stat().st_mode & 0o777 == 0o600

    def test_config_and_state_files_are_private(self, tmp_path):
        from laget_cli.cli import _sync_state, _write_env

        config = tmp_path / "config.env"
        state = tmp_path / "state.json"
        teams = [{"name": "P2021", "club": "Club", "team_slug": "Club-P2021"}]
        children = [{"name": "Alice", "id": "123"}]

        with patch("laget_cli.cli.CONFIG_FILE", config):
            _write_env("t@t.com", "pw")
        with patch("laget_cli.cli.STATE_FILE", state), \
             patch("laget_cli.cli.sync_child_team_mapping", return_value={"123": "Club-P2021"}):
            _sync_state(MagicMock(), {}, teams=teams, children=children, quiet=True)

        assert config.stat().st_mode & 0o777 == 0o600
        assert state.stat().st_mode & 0o777 == 0o600

    def test_config_credentials_round_trip_without_interpolation(self, tmp_path):
        from laget_cli.cli import _load_config, _write_env

        config = tmp_path / "config.env"
        password = r'abc${HOME}\quoted"value'

        with patch("laget_cli.cli.CONFIG_FILE", config):
            _write_env("t@t.com", password)
            loaded = _load_config()

        assert loaded["LAGET_PASSWORD"] == password

    def test_legacy_environment_credentials_warn(self, capsys):
        from laget_cli.cli import _credentials_from_mapping

        with patch("laget_cli.cli._legacy_credentials_warned", False):
            assert _credentials_from_mapping(
                {"EMAIL": "t@t.com", "PASSWORD": "pw"},
                "the environment",
                warn_legacy=True,
            ) == ("t@t.com", "pw")
        assert "deprecated" in capsys.readouterr().err

    def test_legacy_config_does_not_break_structured_error(self, capsys):
        with patch("laget_cli.cli._legacy_credentials_warned", False), \
             patch("laget_cli.cli.dotenv_values", return_value={"EMAIL": "t@t.com", "PASSWORD": "pw"}), \
             patch("laget_cli.cli.login", side_effect=AuthError("Login failed")):
            with patch("sys.argv", ["laget", "status", "--json", "-q"]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 3
        assert json.loads(capsys.readouterr().err)["error"] == "auth_failed"

    def test_legacy_environment_warning_is_quiet(self, capsys):
        from laget_cli.cli import _credentials_from_mapping

        with patch("laget_cli.cli._legacy_credentials_warned", False):
            _credentials_from_mapping(
                {"EMAIL": "t@t.com", "PASSWORD": "pw"},
                "the environment",
                warn_legacy=True,
                quiet=True,
            )
        assert capsys.readouterr().err == ""


class TestUnexpectedErrors:
    def test_unexpected_error_is_structured_without_debug(self, capsys):
        with patch("sys.argv", ["laget", "notifications"]), \
             patch("laget_cli.cli._notifications", side_effect=RuntimeError("internal detail")):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1
        error = json.loads(capsys.readouterr().err)
        assert error["error"] == "unexpected_error"
        assert "internal detail" not in error["message"]

    def test_debug_reraises_unexpected_error(self, capsys):
        with patch("sys.argv", ["laget", "--debug", "notifications"]), \
             patch("laget_cli.cli._notifications", side_effect=RuntimeError("internal detail")):
            with pytest.raises(RuntimeError, match="internal detail"):
                main()
        assert "sensitive data" in capsys.readouterr().err

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from laget_cli.errors import AuthError
from laget_cli.session import (
    API_URL,
    APP_HEADERS,
    HTTP_TIMEOUT,
    LagetSession,
    load_session,
    login,
    new_session,
    save_session,
    verify_authenticated,
)


def response(status=200, payload=None, headers=None):
    result = MagicMock()
    result.status_code = status
    result.headers = headers or {}
    result.json.return_value = {} if payload is None else payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class TestLagetSessionDeadline:
    def test_clamps_each_request_to_remaining_budget(self):
        session = LagetSession(deadline=125)
        with patch("laget_cli.session.time.monotonic", side_effect=[100, 101, 110, 111]), \
             patch.object(requests.Session, "request", return_value=MagicMock()) as request:
            session.get("https://example.com/one", timeout=30)
            session.get("https://example.com/two", timeout=30)

        first = request.call_args_list[0].kwargs["timeout"]
        second = request.call_args_list[1].kwargs["timeout"]
        assert (first.total, first.connect_timeout, first.read_timeout) == (25, 25, 25)
        assert (second.total, second.connect_timeout, second.read_timeout) == (15, 15, 15)

    def test_raises_before_request_when_budget_is_exhausted(self):
        session = LagetSession(deadline=100)
        with patch("laget_cli.session.time.monotonic", return_value=100), \
             patch.object(requests.Session, "request") as request:
            with pytest.raises(requests.Timeout, match="deadline"):
                session.get("https://example.com")
        request.assert_not_called()

    def test_raises_when_request_consumes_remaining_budget(self):
        session = LagetSession(deadline=125)
        with patch("laget_cli.session.time.monotonic", side_effect=[100, 125]), \
             patch.object(requests.Session, "request", return_value=MagicMock()):
            with pytest.raises(requests.Timeout, match="deadline"):
                session.get("https://example.com")


class TestNewSession:
    def test_sets_official_app_headers(self):
        session = new_session()
        for name, value in APP_HEADERS.items():
            assert session.headers[name] == value
        assert session.auth_token is None
        assert session.user_id is None


class TestVerifyAuthenticated:
    def test_uses_me_endpoint_and_returns_json(self):
        session = MagicMock()
        session.get.return_value = response(payload={"id": 123})
        assert verify_authenticated(session) == {"id": 123}
        session.get.assert_called_once_with(f"{API_URL}/v3/users/me", timeout=HTTP_TIMEOUT)

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_status_raises_auth_error(self, status):
        session = MagicMock()
        session.get.return_value = response(status=status)
        with pytest.raises(AuthError, match=str(status)):
            verify_authenticated(session)

    def test_server_error_remains_http_error(self):
        session = MagicMock()
        session.get.return_value = response(status=503)
        with pytest.raises(requests.HTTPError):
            verify_authenticated(session)

    def test_non_json_remains_http_error(self):
        session = MagicMock()
        result = response()
        result.json.side_effect = ValueError("not json")
        session.get.return_value = result
        with pytest.raises(requests.HTTPError):
            verify_authenticated(session)


class TestSessionPersistence:
    def test_save_and_load_v2_roundtrip_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "session.json")
            session = new_session()
            session.auth_token = "secret-token"
            session.user_id = "123"
            session.headers["Auth-Token"] = session.auth_token

            save_session(session, path)
            assert os.stat(path).st_mode & 0o777 == 0o600
            with open(path, encoding="utf-8") as file:
                assert json.load(file) == {
                    "version": 2,
                    "auth_token": "secret-token",
                    "user_id": "123",
                }

            loaded = new_session()
            assert load_session(loaded, path) is True
            assert loaded.auth_token == "secret-token"
            assert loaded.user_id == "123"
            assert loaded.headers["Auth-Token"] == "secret-token"

    def test_legacy_cookie_array_requires_reauthentication(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            json.dump([{"name": "auth", "value": "old-cookie"}], file)
            path = file.name
        try:
            session = new_session()
            assert load_session(session, path) is False
            assert session.auth_token is None
            assert "Auth-Token" not in session.headers
        finally:
            os.unlink(path)

    @pytest.mark.parametrize("content", ["not json", "{}", '{"version":2}'])
    def test_invalid_session_returns_false(self, content):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            file.write(content)
            path = file.name
        try:
            assert load_session(new_session(), path) is False
        finally:
            os.unlink(path)

    def test_load_nonexistent_returns_false(self):
        assert load_session(new_session(), "/nonexistent/path/session.json") is False


class TestLogin:
    def test_login_posts_json_sets_identity_verifies_and_saves(self):
        session = new_session()
        session.post = MagicMock(return_value=response(
            payload={"userId": 123}, headers={"auth-token": "new-token"}
        ))
        session.get = MagicMock(return_value=response(payload={"id": 123}))

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "session.json")
            assert login("test@example.com", "password", path, _session=session) is session
            session.post.assert_called_once_with(
                f"{API_URL}/v1/session",
                json={"username": "test@example.com", "password": "password"},
                timeout=HTTP_TIMEOUT,
            )
            assert session.headers["Auth-Token"] == "new-token"
            assert session.auth_token == "new-token"
            assert session.user_id == "123"
            assert os.path.exists(path)

    def test_valid_saved_token_skips_login(self):
        session = new_session()
        session.post = MagicMock()
        session.get = MagicMock(return_value=response(payload={"id": 123}))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            json.dump({
                "version": 2,
                "auth_token": "saved-token",
                "user_id": "123",
            }, file)
            path = file.name
        try:
            assert login("test@example.com", "password", path, _session=session) is session
            session.post.assert_not_called()
            assert session.headers["Auth-Token"] == "saved-token"
        finally:
            os.unlink(path)

    def test_expired_saved_token_reauthenticates_once_and_replaces_file(self):
        session = new_session()
        session.get = MagicMock(side_effect=[
            response(status=401),
            response(payload={"id": 123}),
        ])
        session.post = MagicMock(return_value=response(
            payload={"userId": 123}, headers={"auth-token": "replacement"}
        ))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            json.dump({
                "version": 2,
                "auth_token": "expired",
                "user_id": "123",
            }, file)
            path = file.name
        try:
            login("test@example.com", "password", path, _session=session)
            session.post.assert_called_once()
            with open(path, encoding="utf-8") as file:
                assert json.load(file)["auth_token"] == "replacement"
        finally:
            os.unlink(path)

    def test_saved_session_server_error_does_not_attempt_login_or_replace_token(self):
        session = new_session()
        session.get = MagicMock(return_value=response(status=503))
        session.post = MagicMock()
        original = {
            "version": 2,
            "auth_token": "still-valid",
            "user_id": "123",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            json.dump(original, file)
            path = file.name
        try:
            with pytest.raises(requests.HTTPError):
                login("test@example.com", "password", path, _session=session)
            session.post.assert_not_called()
            with open(path, encoding="utf-8") as file:
                assert json.load(file) == original
        finally:
            os.unlink(path)

    @pytest.mark.parametrize("status", [401, 403])
    def test_bad_credentials_raise_auth_without_retry(self, status):
        session = new_session()
        session.post = MagicMock(return_value=response(status=status))
        session.get = MagicMock()
        with pytest.raises(AuthError, match="Authentication failed"):
            login("test@example.com", "wrong", session_path=None, _session=session)
        session.post.assert_called_once()
        session.get.assert_not_called()

    def test_incomplete_login_response_is_auth_error(self):
        session = new_session()
        session.post = MagicMock(return_value=response(payload={"userId": 123}))
        with pytest.raises(AuthError, match="incomplete"):
            login("test@example.com", "password", session_path=None, _session=session)


class TestAutomaticReauthentication:
    def _authenticated_session(self, session_path=None):
        session = new_session()
        session._email = "test@example.com"
        session._password = "password"
        session._session_path = session_path
        session.auth_token = "expired"
        session.user_id = "123"
        session.headers["Auth-Token"] = "expired"
        return session

    def test_401_reauthenticates_verifies_saves_then_replays_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "session.json")
            session = self._authenticated_session(path)
            original_401 = response(status=401)
            login_ok = response(
                payload={"userId": 123}, headers={"auth-token": "replacement"}
            )
            verify_ok = response(payload={"id": 123})
            replay_ok = response(payload={"items": []})

            with patch.object(
                requests.Session,
                "request",
                side_effect=[original_401, login_ok, verify_ok, replay_ok],
            ) as raw_request:
                result = session.get(
                    f"{API_URL}/v4/users/123/teams",
                    params={"include": "active"},
                    timeout=17,
                )

            assert result is replay_ok
            assert raw_request.call_count == 4
            first = raw_request.call_args_list[0]
            replay = raw_request.call_args_list[3]
            assert first.args == replay.args
            assert first.kwargs == replay.kwargs
            assert raw_request.call_args_list[1].args == ("POST", f"{API_URL}/v1/session")
            assert raw_request.call_args_list[2].args == ("GET", f"{API_URL}/v3/users/me")
            with open(path, encoding="utf-8") as file:
                assert json.load(file)["auth_token"] == "replacement"

    def test_mutating_json_request_is_replayed_once_with_identical_body(self):
        session = self._authenticated_session()
        denied = response(status=401)
        login_ok = response(
            payload={"userId": 123}, headers={"auth-token": "replacement"}
        )
        verify_ok = response(payload={"id": 123})
        replay_ok = response(payload={"saved": True})
        body = {
            "siteId": 456,
            "attending": True,
            "answer": "yes",
            "reason": "Kommer",
        }

        with patch.object(
            requests.Session,
            "request",
            side_effect=[denied, login_ok, verify_ok, replay_ok],
        ) as raw_request:
            result = session.put(
                f"{API_URL}/v1/events/789/rsvp/123",
                json=body,
                timeout=HTTP_TIMEOUT,
            )

        assert result is replay_ok
        assert raw_request.call_count == 4
        first_body = raw_request.call_args_list[0].kwargs["json"]
        replay_body = raw_request.call_args_list[3].kwargs["json"]
        assert first_body == replay_body == body

    def test_permission_403_is_not_reauthenticated_or_replayed(self):
        session = self._authenticated_session()
        denied = response(status=403)
        with patch.object(
            requests.Session, "request", return_value=denied
        ) as raw_request:
            result = session.put(
                f"{API_URL}/v1/events/789/rsvp/123",
                json={"attending": 1},
            )
        assert result is denied
        raw_request.assert_called_once()

    def test_replayed_401_does_not_reauthenticate_again(self):
        session = self._authenticated_session()
        responses = [
            response(status=401),
            response(payload={"userId": 123}, headers={"auth-token": "replacement"}),
            response(payload={"id": 123}),
            response(status=401),
        ]
        with patch.object(requests.Session, "request", side_effect=responses) as raw_request:
            with pytest.raises(AuthError, match="after token refresh"):
                session.get(f"{API_URL}/v4/users/123/teams")
        assert raw_request.call_count == 4

    def test_transient_response_does_not_reauthenticate_or_change_disk_token(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            original = {
                "version": 2,
                "auth_token": "still-valid",
                "user_id": "123",
            }
            json.dump(original, file)
            path = file.name
        try:
            session = self._authenticated_session(path)
            with patch.object(
                requests.Session, "request", return_value=response(status=503)
            ) as raw_request:
                result = session.get(f"{API_URL}/v4/users/123/teams")
            assert result.status_code == 503
            assert raw_request.call_count == 1
            with open(path, encoding="utf-8") as file:
                assert json.load(file) == original
        finally:
            os.unlink(path)

    def test_failed_reauth_verification_keeps_disk_token_and_does_not_replay(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            original = {
                "version": 2,
                "auth_token": "expired",
                "user_id": "123",
            }
            json.dump(original, file)
            path = file.name
        try:
            session = self._authenticated_session(path)
            responses = [
                response(status=401),
                response(payload={"userId": 123}, headers={"auth-token": "candidate"}),
                response(status=503),
            ]
            with patch.object(
                requests.Session, "request", side_effect=responses
            ) as raw_request:
                with pytest.raises(requests.HTTPError):
                    session.get(f"{API_URL}/v4/users/123/teams")
            assert raw_request.call_count == 3
            with open(path, encoding="utf-8") as file:
                assert json.load(file) == original
        finally:
            os.unlink(path)

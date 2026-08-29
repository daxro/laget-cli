"""laget.se JSON API session management and token persistence."""

import json
import os
import time
from copy import deepcopy
from urllib.parse import urlparse

import requests
from urllib3.util import Timeout

from laget_cli.errors import AuthError
from laget_cli.paths import atomic_write_text

API_URL = "https://api.laget.se"
HTTP_TIMEOUT = 60
SESSION_VERSION = 2

APP_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Lagetse-App-Version": "3.3.7",
    "Lagetse-App-Build-Version": "939",
    "Lagetse-App-Platform": "android",
}


class LagetSession(requests.Session):
    """API session with identity state and an optional shared request deadline."""

    def __init__(self, deadline=None):
        super().__init__()
        self.deadline = deadline
        self.auth_token = None
        self.user_id = None
        self._email = None
        self._password = None
        self._session_path = None
        self._reauthenticating = False

    def request(self, method, url, **kwargs):
        skip_reauth = kwargs.pop("_laget_skip_reauth", False)
        replay_kwargs = _copy_request_kwargs(kwargs)
        response = self._request_once(method, url, **kwargs)
        if (
            response.status_code == 401
            and not skip_reauth
            and not self._reauthenticating
            and urlparse(url).path.rstrip("/") != "/v1/session"
            and self._email is not None
            and self._password is not None
        ):
            response.close()
            self._reauthenticating = True
            try:
                _clear_identity(self)
                _login_with_credentials(self, self._email, self._password)
                verify_authenticated(self)
                if self._session_path:
                    save_session(self, self._session_path)
            finally:
                self._reauthenticating = False
            # Use the low-level path so a second 401/403 is returned directly.
            response = self._request_once(method, url, **replay_kwargs)
            if response.status_code == 401:
                response.close()
                raise AuthError(
                    f"Authentication failed after token refresh ({response.status_code})"
                )
        return response

    def _request_once(self, method, url, **kwargs):
        if self.deadline is None:
            return super().request(method, url, **kwargs)

        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Network deadline exceeded")

        configured = kwargs.get("timeout", HTTP_TIMEOUT)
        if isinstance(configured, tuple):
            connect, read = configured
        else:
            connect = read = configured
        connect = remaining if connect is None else min(connect, remaining)
        read = remaining if read is None else min(read, remaining)
        kwargs["timeout"] = Timeout(total=remaining, connect=connect, read=read)

        response = super().request(method, url, **kwargs)
        if time.monotonic() >= self.deadline:
            raise requests.Timeout("Network deadline exceeded")
        return response


def _copy_request_kwargs(kwargs):
    """Copy API request inputs before requests prepares a possible replay."""
    copied = dict(kwargs)
    for key in ("headers", "params", "json", "data"):
        value = copied.get(key)
        if isinstance(value, (dict, list, tuple)):
            copied[key] = deepcopy(value)
    return copied


def new_session(deadline=None):
    """Create a session configured like the official Android JSON API client."""
    session = LagetSession(deadline=deadline)
    session.headers.update(APP_HEADERS)
    return session


def _set_identity(session, auth_token, user_id):
    """Attach a validated API identity to a session."""
    session.auth_token = str(auth_token)
    session.user_id = str(user_id)
    session.headers["Auth-Token"] = session.auth_token


def _clear_identity(session):
    session.auth_token = None
    session.user_id = None
    session.headers.pop("Auth-Token", None)


def save_session(session, path="session.json"):
    """Persist the API token and user ID atomically with private permissions."""
    auth_token = getattr(session, "auth_token", None)
    user_id = getattr(session, "user_id", None)
    if not isinstance(auth_token, str) or not auth_token:
        raise ValueError("Cannot save a session without an auth token")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Cannot save a session without a user ID")
    payload = {
        "version": SESSION_VERSION,
        "auth_token": auth_token,
        "user_id": user_id,
    }
    atomic_write_text(path, json.dumps(payload, indent=2))


def load_session(session, path="session.json"):
    """Load a v2 API session; legacy cookie arrays deliberately require login."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as file:
            payload = json.load(file)
    except (json.JSONDecodeError, OSError):
        return False

    # v1 was a list of web cookies. It cannot authenticate the JSON API.
    if not isinstance(payload, dict) or payload.get("version") != SESSION_VERSION:
        return False
    auth_token = payload.get("auth_token")
    user_id = payload.get("user_id")
    if not isinstance(auth_token, str) or not auth_token:
        return False
    if not isinstance(user_id, str) or not user_id:
        return False
    _set_identity(session, auth_token, user_id)
    return True


def verify_authenticated(session):
    """Verify a token without misclassifying transient failures as expiry."""
    request_kwargs = {"timeout": HTTP_TIMEOUT}
    if isinstance(session, LagetSession):
        request_kwargs["_laget_skip_reauth"] = True
    response = session.get(f"{API_URL}/v3/users/me", **request_kwargs)
    if response.status_code in (401, 403):
        raise AuthError(f"Session expired - auth check returned {response.status_code}")
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise requests.HTTPError(
            "Auth check returned an unexpected response",
            response=response,
        ) from error
    if not isinstance(payload, dict):
        raise requests.HTTPError(
            "Auth check returned an unexpected response",
            response=response,
        )
    return payload


def _login_with_credentials(session, email, password):
    response = session.post(
        f"{API_URL}/v1/session",
        json={"username": email, "password": password},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code in (401, 403):
        raise AuthError("Authentication failed")
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise requests.HTTPError(
            "Login returned an unexpected response",
            response=response,
        ) from error

    auth_token = response.headers.get("auth-token")
    user_id = payload.get("userId") if isinstance(payload, dict) else None
    if not auth_token or user_id is None:
        raise AuthError("Authentication response was incomplete")
    _set_identity(session, auth_token, user_id)


def login(email, password, session_path="session.json", _session=None, deadline_seconds=None):
    """Return an authenticated API session, reauthenticating an expired token once."""
    deadline = (
        time.monotonic() + deadline_seconds
        if deadline_seconds is not None
        else None
    )
    session = _session or new_session(deadline=deadline)
    if deadline is not None and isinstance(session, LagetSession):
        session.deadline = deadline
    if isinstance(session, LagetSession):
        session._email = email
        session._password = password
        session._session_path = session_path

    if session_path and load_session(session, session_path):
        try:
            verify_authenticated(session)
            return session
        except AuthError:
            # A definitive 401/403 permits one credential login. The old token
            # remains safely on disk until the replacement has been verified.
            _clear_identity(session)

    _login_with_credentials(session, email, password)
    verify_authenticated(session)

    if session_path:
        save_session(session, session_path)
    return session

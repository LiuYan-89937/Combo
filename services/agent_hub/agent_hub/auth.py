from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from base64 import urlsafe_b64encode
import hmac
import secrets
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken

from agent_hub.config import Settings
from agent_hub.database import Database, utc_now


GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
SESSION_COOKIE = "agenthub_session"
OAUTH_STATE_COOKIE = "agenthub_oauth_state"
DESKTOP_AUTH_POLL_INTERVAL_SECONDS = 3


class AuthenticationError(PermissionError):
    pass


class AuthorizationPending(RuntimeError):
    def __init__(self, code: str, message: str, *, retry_after_seconds: int = 5) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class OAuthLoginCompletion:
    user: dict[str, Any]
    session_token: str | None
    flow_kind: str
    return_to: str | None


class AuthService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self._provider_token_cipher = Fernet(
            urlsafe_b64encode(sha256(settings.github_client_secret.encode("utf-8")).digest())
        )

    def github_login_url(self, *, return_to: str | None = None) -> tuple[str, str]:
        if not self.settings.github_oauth_configured:
            raise AuthenticationError("GitHub OAuth is not configured")
        normalized_return_to = _safe_return_to(return_to)
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.settings.oauth_state_ttl_seconds)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            self._remove_expired_auth_flows(connection, now=now)
            connection.execute(
                """
                insert into oauth_states(
                  state_hash, flow_kind, desktop_flow_id, return_to, expires_at, created_at
                ) values (?, 'browser', null, ?, ?, ?)
                """,
                (
                    _token_hash(state),
                    normalized_return_to,
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.commit()
        return self._github_authorization_url(state), state

    def start_github_desktop_login(self) -> dict[str, Any]:
        if not self.settings.github_oauth_configured:
            raise AuthenticationError("GitHub OAuth is not configured")
        flow_id = uuid4().hex
        poll_secret = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.settings.oauth_state_ttl_seconds)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            self._remove_expired_auth_flows(connection, now=now)
            connection.execute(
                """
                insert into desktop_auth_flows(
                  flow_id, poll_secret_hash, status, user_id, expires_at,
                  authorized_at, provider_token_ciphertext, created_at
                ) values (?, ?, 'pending', null, ?, null, null, ?)
                """,
                (
                    flow_id,
                    _token_hash(poll_secret),
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.execute(
                """
                insert into oauth_states(
                  state_hash, flow_kind, desktop_flow_id, return_to, expires_at, created_at
                ) values (?, 'desktop', ?, null, ?, ?)
                """,
                (
                    _token_hash(state),
                    flow_id,
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.commit()
        return {
            "flow_id": flow_id,
            "poll_secret": poll_secret,
            "authorization_url": self._github_authorization_url(state),
            "expires_in": self.settings.oauth_state_ttl_seconds,
            "interval": DESKTOP_AUTH_POLL_INTERVAL_SECONDS,
        }

    def complete_github_login(
        self,
        *,
        code: str,
        state: str,
        state_cookie: str | None,
    ) -> OAuthLoginCompletion:
        code = str(code or "").strip()
        state = str(state or "").strip()
        if not code or not state:
            raise AuthenticationError("GitHub OAuth callback is missing code or state")
        oauth_state = self._consume_oauth_state(state, state_cookie=state_cookie)
        profile, provider_token = self._github_profile(code)
        user = self._upsert_github_user(profile)
        flow_kind = str(oauth_state["flow_kind"])
        if flow_kind == "desktop":
            flow_id = str(oauth_state["desktop_flow_id"] or "")
            now = utc_now()
            with self.database.connect() as connection:
                provider_token_ciphertext = self._provider_token_cipher.encrypt(
                    provider_token.encode("utf-8")
                ).decode("ascii")
                result = connection.execute(
                    """
                    update desktop_auth_flows
                    set status = 'authorized', user_id = ?, authorized_at = ?,
                        provider_token_ciphertext = ?
                    where flow_id = ? and status = 'pending' and expires_at > ?
                    """,
                    (str(user["user_id"]), now, provider_token_ciphertext, flow_id, now),
                )
            if result.rowcount != 1:
                raise AuthenticationError("desktop login flow is invalid or expired")
            return OAuthLoginCompletion(
                user=user,
                session_token=None,
                flow_kind="desktop",
                return_to=None,
            )
        token = self.create_session(str(user["user_id"]))
        return OAuthLoginCompletion(
            user=user,
            session_token=token,
            flow_kind="browser",
            return_to=str(oauth_state["return_to"] or "") or None,
        )

    def poll_github_desktop_login(
        self,
        *,
        flow_id: str,
        poll_secret: str,
    ) -> tuple[dict[str, Any], str, str]:
        flow_id = str(flow_id or "").strip()
        poll_secret = str(poll_secret or "").strip()
        if not flow_id or not poll_secret:
            raise AuthenticationError("desktop login credentials are required")
        now = datetime.now(timezone.utc)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            self._remove_expired_auth_flows(connection, now=now)
            row = connection.execute(
                """
                select *
                from desktop_auth_flows
                where flow_id = ? and poll_secret_hash = ? and expires_at > ?
                """,
                (flow_id, _token_hash(poll_secret), now.isoformat()),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise AuthenticationError("desktop login flow is invalid or expired")
            if str(row["status"]) == "pending":
                connection.rollback()
                raise AuthorizationPending(
                    "authorization_pending",
                    "waiting for GitHub authorization",
                    retry_after_seconds=DESKTOP_AUTH_POLL_INTERVAL_SECONDS,
                )
            user_id = str(row["user_id"] or "")
            provider_token_ciphertext = str(row["provider_token_ciphertext"] or "")
            if not provider_token_ciphertext:
                connection.rollback()
                raise AuthenticationError("GitHub authorization token is unavailable; sign in again")
            try:
                provider_token = self._provider_token_cipher.decrypt(
                    provider_token_ciphertext.encode("ascii")
                ).decode("utf-8")
            except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
                connection.rollback()
                raise AuthenticationError(
                    "GitHub authorization token could not be opened; sign in again"
                ) from exc
            user = connection.execute(
                "select * from users where user_id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                connection.rollback()
                raise AuthenticationError("authorized GitHub user was not found")
            token = self._create_session(connection, user_id=user_id, now=now)
            connection.execute(
                "delete from desktop_auth_flows where flow_id = ?",
                (flow_id,),
            )
            connection.commit()
        return dict(user), token, provider_token

    def cancel_github_desktop_login(self, *, flow_id: str, poll_secret: str) -> None:
        flow_id = str(flow_id or "").strip()
        poll_secret = str(poll_secret or "").strip()
        if not flow_id or not poll_secret:
            return
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select flow_id
                from desktop_auth_flows
                where flow_id = ? and poll_secret_hash = ?
                """,
                (flow_id, _token_hash(poll_secret)),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "delete from oauth_states where desktop_flow_id = ?",
                    (flow_id,),
                )
                connection.execute(
                    "delete from desktop_auth_flows where flow_id = ?",
                    (flow_id,),
                )
            connection.commit()

    def start_github_device_login(self) -> dict[str, Any]:
        if not self.settings.github_oauth_configured:
            raise AuthenticationError("GitHub OAuth is not configured")
        with httpx.Client(timeout=20) as client:
            response = client.post(
                GITHUB_DEVICE_CODE_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_client_id,
                    "scope": "read:user repo",
                },
            )
            payload = _response_object(response, "GitHub device authorization failed")
        required = ("device_code", "user_code", "verification_uri", "expires_in", "interval")
        if not isinstance(payload, dict) or any(not payload.get(key) for key in required):
            raise AuthenticationError("GitHub returned an invalid device authorization")
        return {
            "device_code": str(payload["device_code"]),
            "user_code": str(payload["user_code"]),
            "verification_uri": str(payload["verification_uri"]),
            "expires_in": int(payload["expires_in"]),
            "interval": max(5, int(payload["interval"])),
        }

    def poll_github_device_login(self, device_code: str) -> tuple[dict[str, Any], str, str]:
        code = str(device_code or "").strip()
        if not code:
            raise AuthenticationError("GitHub device code is required")
        with httpx.Client(timeout=20) as client:
            response = client.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_client_id,
                    "device_code": code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise AuthenticationError("GitHub returned an invalid device authorization response")
        error = str(payload.get("error") or "").strip()
        if error:
            retry_after = 10 if error == "slow_down" else 5
            if error in {"authorization_pending", "slow_down"}:
                raise AuthorizationPending(
                    error,
                    str(payload.get("error_description") or error),
                    retry_after_seconds=retry_after,
                )
            raise AuthenticationError(str(payload.get("error_description") or error))
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise AuthenticationError("GitHub did not return an access token")
        profile = self._github_profile_from_token(access_token)
        user = self._upsert_github_user(profile)
        return user, self.create_session(str(user["user_id"])), access_token

    def authenticate(self, *, bearer_token: str | None, cookie_token: str | None) -> dict[str, Any]:
        bearer = str(bearer_token or "").strip()
        if bearer and self.settings.admin_token and hmac.compare_digest(
            bearer,
            self.settings.admin_token,
        ):
            return self._bootstrap_admin_user()
        token = bearer or str(cookie_token or "").strip()
        if not token:
            raise AuthenticationError("authentication required")
        now = utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                select users.*
                from sessions
                join users on users.user_id = sessions.user_id
                where sessions.session_hash = ? and sessions.expires_at > ?
                """,
                (_token_hash(token), now),
            ).fetchone()
        if row is None:
            raise AuthenticationError("session is invalid or expired")
        return dict(row)

    def create_session(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        with self.database.connect() as connection:
            return self._create_session(connection, user_id=user_id, now=now)

    def delete_session(self, token: str) -> None:
        if not token:
            return
        with self.database.connect() as connection:
            connection.execute(
                "delete from sessions where session_hash = ?",
                (_token_hash(token),),
            )

    def require_admin(self, user: dict[str, Any]) -> None:
        if not bool(user.get("is_admin")):
            raise AuthenticationError("administrator access required")

    def _consume_oauth_state(
        self,
        state: str,
        *,
        state_cookie: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        state_hash = _token_hash(state)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select state_hash, flow_kind, desktop_flow_id, return_to
                from oauth_states
                where state_hash = ? and expires_at > ?
                """,
                (state_hash, now),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise AuthenticationError("GitHub OAuth state is invalid or expired")
            if str(row["flow_kind"]) == "browser":
                cookie = str(state_cookie or "")
                if not cookie or not hmac.compare_digest(state, cookie):
                    connection.rollback()
                    raise AuthenticationError(
                        "GitHub OAuth state cookie is invalid or expired"
                    )
            connection.execute(
                "delete from oauth_states where state_hash = ?",
                (state_hash,),
            )
            connection.commit()
        return dict(row)

    def _github_authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": f"{self.settings.base_url}/api/v1/auth/github/callback",
                "scope": "read:user repo",
                "state": state,
            }
        )
        return f"{GITHUB_AUTHORIZE_URL}?{query}"

    def _create_session(
        self,
        connection,
        *,
        user_id: str,
        now: datetime,
    ) -> str:
        token = secrets.token_urlsafe(32)
        expires = now + timedelta(seconds=self.settings.session_ttl_seconds)
        connection.execute(
            """
            insert into sessions(session_hash, user_id, expires_at, created_at)
            values (?, ?, ?, ?)
            """,
            (_token_hash(token), user_id, expires.isoformat(), now.isoformat()),
        )
        return token

    @staticmethod
    def _remove_expired_auth_flows(connection, *, now: datetime) -> None:
        timestamp = now.isoformat()
        connection.execute(
            "delete from oauth_states where expires_at <= ?",
            (timestamp,),
        )
        connection.execute(
            "delete from desktop_auth_flows where expires_at <= ?",
            (timestamp,),
        )

    def _github_profile(self, code: str) -> tuple[dict[str, Any], str]:
        with httpx.Client(timeout=20) as client:
            token_response = client.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    "code": code,
                    "redirect_uri": (
                        f"{self.settings.base_url}/api/v1/auth/github/callback"
                    ),
                },
            )
            token_response.raise_for_status()
            access_token = str(token_response.json().get("access_token") or "").strip()
            if not access_token:
                raise AuthenticationError("GitHub did not return an access token")
        return self._github_profile_from_token(access_token), access_token

    def _github_profile_from_token(self, access_token: str) -> dict[str, Any]:
        with httpx.Client(timeout=20) as client:
            profile_response = client.get(
                GITHUB_USER_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
        if not isinstance(profile, dict) or not profile.get("id") or not profile.get("login"):
            raise AuthenticationError("GitHub returned an invalid user profile")
        return profile

    def _upsert_github_user(self, profile: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        github_id = int(profile["id"])
        login = str(profile["login"]).strip()
        user_id = f"github:{github_id}"
        is_admin = int(login.casefold() in self.settings.admin_github_logins)
        with self.database.connect() as connection:
            connection.execute(
                """
                insert into users(
                  user_id, github_id, github_login, display_name, avatar_url,
                  is_admin, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(user_id) do update set
                  github_login = excluded.github_login,
                  display_name = excluded.display_name,
                  avatar_url = excluded.avatar_url,
                  is_admin = excluded.is_admin,
                  updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    github_id,
                    login,
                    str(profile.get("name") or login)[:200],
                    str(profile.get("avatar_url") or "")[:1_000],
                    is_admin,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "select * from users where user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row)

    def _bootstrap_admin_user(self) -> dict[str, Any]:
        now = utc_now()
        user_id = "bootstrap:admin"
        with self.database.connect() as connection:
            connection.execute(
                """
                insert into users(
                  user_id, github_id, github_login, display_name, avatar_url,
                  is_admin, created_at, updated_at
                ) values (?, null, ?, ?, '', 1, ?, ?)
                on conflict(user_id) do update set
                  is_admin = 1,
                  updated_at = excluded.updated_at
                """,
                (user_id, "bootstrap-admin", "Bootstrap Administrator", now, now),
            )
            row = connection.execute(
                "select * from users where user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row)


def public_user_view(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(user.get("user_id") or ""),
        "github_login": str(user.get("github_login") or ""),
        "display_name": str(user.get("display_name") or ""),
        "avatar_url": str(user.get("avatar_url") or ""),
        "is_admin": bool(user.get("is_admin")),
    }


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _safe_return_to(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if (
        parsed.scheme
        or parsed.netloc
        or not normalized.startswith("/")
        or normalized.startswith("//")
        or "\\" in normalized
        or any(ord(character) < 32 for character in normalized)
    ):
        raise AuthenticationError("OAuth return path must be an absolute-path reference")
    return normalized


def _response_object(response: httpx.Response, fallback_message: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthenticationError(fallback_message) from exc
    if not isinstance(payload, dict):
        raise AuthenticationError(fallback_message)
    if response.is_error:
        raise AuthenticationError(
            str(payload.get("error_description") or payload.get("error") or fallback_message)
        )
    return payload

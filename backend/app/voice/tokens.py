"""Minting short-lived Gemini Live tokens.

The browser never sees GEMINI_API_KEY. It gets an ephemeral token that:
- can start exactly one session (uses=1),
- must be used to connect within 1 minute,
- stops working after the session length (max 15 minutes),
- is locked to this model and this exact config (instructions, tools, voice),
  so the browser can't rewrite Aria's instructions or add tools.

Docs: https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from ..config import Settings


class VoiceNotConfiguredError(Exception):
    """GEMINI_API_KEY isn't set."""


class VoiceProviderError(Exception):
    """Google refused or failed to mint a token."""


@dataclass(frozen=True)
class MintedToken:
    name: str
    expires_at: datetime
    new_session_expires_at: datetime


class TokenMinter(Protocol):
    def mint(self, *, model: str, config: dict[str, Any], now: datetime, session_minutes: int) -> MintedToken: ...


NEW_SESSION_WINDOW = timedelta(minutes=1)


class GeminiTokenMinter:
    """Real minter, using the google-genai SDK. Created lazily so tests never import a network client."""

    def __init__(self, settings: Settings) -> None:
        if settings.gemini_api_key is None:
            raise VoiceNotConfiguredError
        self._api_key = settings.gemini_api_key
        self._api_version = settings.gemini_api_version

    def mint(self, *, model: str, config: dict[str, Any], now: datetime, session_minutes: int) -> MintedToken:
        from google import genai
        from google.genai import types

        expires_at = now + timedelta(minutes=session_minutes)
        new_session_expires_at = now + NEW_SESSION_WINDOW
        client = genai.Client(
            api_key=self._api_key.get_secret_value(),
            http_options=types.HttpOptions(api_version=self._api_version),
        )
        try:
            token = client.auth_tokens.create(
                config=types.CreateAuthTokenConfig(
                    uses=1,
                    expire_time=expires_at,
                    new_session_expire_time=new_session_expires_at,
                    # No lock_additional_fields: per the SDK, the whole config is then locked.
                    live_connect_constraints=types.LiveConnectConstraints(
                        model=model, config=types.LiveConnectConfig.model_validate(config)
                    ),
                )
            )
        except Exception as exc:  # the SDK raises several error types; never echo their text
            raise VoiceProviderError(type(exc).__name__) from None
        if not token.name:
            raise VoiceProviderError("empty token")
        return MintedToken(token.name, expires_at, new_session_expires_at)

"""Configuration, read from environment variables (and backend/.env if present)."""

from functools import cached_property
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Prebuilt Gemini voices, from https://ai.google.dev/gemini-api/docs/speech-generation
GEMINI_VOICES = frozenset(
    [
        "Zephyr",
        "Puck",
        "Charon",
        "Kore",
        "Fenrir",
        "Leda",
        "Orus",
        "Aoede",
        "Callirrhoe",
        "Autonoe",
        "Enceladus",
        "Iapetus",
        "Umbriel",
        "Algieba",
        "Despina",
        "Erinome",
        "Algenib",
        "Rasalgethi",
        "Laomedeia",
        "Achernar",
        "Alnilam",
        "Schedar",
        "Gacrux",
        "Pulcherrima",
        "Achird",
        "Zubenelgenubi",
        "Vindemiatrix",
        "Sadachbia",
        "Sadaltager",
        "Sulafat",
    ]
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # Where the SQLite demo database lives. Relative paths resolve from backend/.
    database_path: Path = Field(default=Path("data/aura.db"))

    # Comma-separated list of browser origins allowed to call the API.
    # Defaults cover the Vite dev server (5173) and `npm run preview` (4173).
    allowed_origins: str = "http://localhost:5173,http://localhost:4173"

    # Time zone used for "today", "6 PM" and day counts. Aura is an Indian brand.
    app_timezone: str = "Asia/Kolkata"

    log_level: str = "INFO"

    # ── Voice (Phase 4) ──────────────────────────────────────────────────
    # Server-side only. Never sent to the browser, logged or returned by the API:
    # the browser gets a short-lived, single-use ephemeral token instead.
    gemini_api_key: SecretStr | None = None
    gemini_live_model: str = "gemini-3.8-live"
    # Google's ephemeral-token docs say v1beta; the SDKs still mention v1alpha.
    # One setting drives both token minting and the browser connection.
    gemini_api_version: Literal["v1beta", "v1alpha"] = "v1beta"
    gemini_voice: str = "Sulafat"
    # Gemini caps audio-only Live sessions at 15 minutes.
    voice_session_minutes: int = Field(default=15, ge=1, le=15)
    # Simple per-IP limit on new voice sessions (each one mints a token).
    voice_sessions_per_ip_per_hour: int = Field(default=30, ge=1, le=1000)

    @field_validator("app_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"APP_TIMEZONE '{value}' is not a known IANA time zone") from exc
        return value

    @field_validator("gemini_voice")
    @classmethod
    def _valid_voice(cls, value: str) -> str:
        if value not in GEMINI_VOICES:
            raise ValueError(f"GEMINI_VOICE '{value}' is not a Gemini prebuilt voice")
        return value

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        return value

    @cached_property
    def database_file(self) -> Path:
        path = self.database_path
        return path if path.is_absolute() else BACKEND_DIR / path

    @cached_property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

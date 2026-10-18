"""Shared fixtures.

Every test gets its own temporary SQLite file and a frozen, movable clock, so
tests never touch the demo database (backend/data/aura.db) and never depend on
the real time of day.
"""

import importlib.util
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import BACKEND_DIR, Settings
from app.main import create_app
from app.voice.tokens import MintedToken, VoiceProviderError

# Every package in requirements-dev.txt that the tests import. If one is missing,
# stop the whole run: a partial pass that silently drops the voice tests is not a pass.
REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "pydantic_settings": "pydantic-settings",
    "google.genai": "google-genai",
    "httpx2": "httpx2",
    "tzdata": "tzdata",
}


def _is_installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:  # the parent package (e.g. "google") is missing
        return False


def pytest_configure(config: pytest.Config) -> None:
    missing = sorted(pkg for module, pkg in REQUIRED_MODULES.items() if not _is_installed(module))
    if missing:
        raise pytest.UsageError(
            f"Missing test dependencies: {', '.join(missing)}. From backend/, with the virtual "
            "environment active, run: pip install -r requirements-dev.txt"
        )


# 10:00 IST on 17 Oct 2026, so "6 PM today" is still ahead.
SEED_TIME = datetime(2026, 10, 17, 4, 30, tzinfo=UTC)
DEMO_DB = BACKEND_DIR / "data" / "aura.db"


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture(autouse=True)
def _isolate_from_demo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the default DATABASE_PATH at a temp file and prove the demo DB is untouched."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "default-from-env.db"))
    before = DEMO_DB.stat().st_mtime_ns if DEMO_DB.exists() else None
    yield
    after = DEMO_DB.stat().st_mtime_ns if DEMO_DB.exists() else None
    assert before == after, "a test modified the demo database"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def settings(db_path: Path) -> Settings:
    return Settings(
        database_path=db_path, allowed_origins="http://localhost:5173", app_timezone="Asia/Kolkata", log_level="WARNING"
    )


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(SEED_TIME)


@pytest.fixture
def client(settings: Settings, clock: FrozenClock) -> Iterator[TestClient]:
    """App with a freshly seeded temp database (the lifespan seeds it at SEED_TIME)."""
    with TestClient(create_app(settings, clock)) as test_client:
        yield test_client


@pytest.fixture
def conn(client: TestClient, db_path: Path) -> Iterator[sqlite3.Connection]:
    """A direct connection to the same temp database the client uses."""
    with closing(db.connect(db_path)) as connection:
        yield connection


@pytest.fixture
def order_status(conn: sqlite3.Connection) -> Callable[[str], str]:
    def read(order_id: str) -> str:
        return str(conn.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,)).fetchone()[0])

    return read


# ── Phase 4: voice ──────────────────────────────────────────────────────────


class FakeMinter:
    """Stands in for Google's token service. Records what it was asked to lock."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def mint(self, *, model: str, config: dict[str, Any], now: datetime, session_minutes: int) -> MintedToken:
        self.calls.append({"model": model, "config": config, "now": now, "session_minutes": session_minutes})
        if self.fail:
            raise VoiceProviderError("FakeProviderDown")
        return MintedToken(
            f"auth_tokens/fake-{len(self.calls)}",
            now + timedelta(minutes=session_minutes),
            now + timedelta(minutes=1),
        )


@pytest.fixture
def minter() -> FakeMinter:
    return FakeMinter()


@pytest.fixture
def voice_client(settings: Settings, clock: FrozenClock, minter: FakeMinter) -> Iterator[TestClient]:
    with TestClient(create_app(settings, clock, token_minter_factory=lambda: minter)) as test_client:
        yield test_client


class Call:
    """A started voice session, with helpers for its secret-authenticated routes."""

    def __init__(self, client: TestClient, body: dict[str, Any]) -> None:
        self.client = client
        self.body = body
        self.id: str = body["session_id"]
        self.headers = {"X-Session-Secret": body["session_secret"]}
        self._n = 0

    def tool(self, name: str, **args: Any) -> dict[str, Any]:
        self._n += 1
        r = self.client.post(
            f"/api/voice/sessions/{self.id}/tool-calls",
            json={"call_id": f"c{self._n}", "name": name, "args": args},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        response: dict[str, Any] = r.json()["response"]
        return response

    def end(self, transcript: list[tuple[str, str]] | None = None, **extra: Any) -> dict[str, Any]:
        turns = [{"speaker": s, "text": t} for s, t in (transcript or [])]
        r = self.client.post(
            f"/api/voice/sessions/{self.id}/end", json={"transcript": turns, **extra}, headers=self.headers
        )
        assert r.status_code == 200, r.text
        result: dict[str, Any] = r.json()
        return result


@pytest.fixture
def start_call(voice_client: TestClient) -> Callable[[], Call]:
    def start() -> Call:
        r = voice_client.post("/api/voice/sessions")
        assert r.status_code == 201, r.text
        return Call(voice_client, r.json())

    return start

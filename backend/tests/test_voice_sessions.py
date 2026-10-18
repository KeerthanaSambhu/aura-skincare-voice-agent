"""Phase 4: starting voice sessions, and keeping the Gemini API key secret."""

import io
import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.config import Settings
from app.main import create_app
from app.policies import CANCELLATION_POLICY, COD_POLICY, RETURN_POLICY, SHIPPING_POLICY
from app.voice.prompt import TOOL_DECLARATIONS, build_live_config
from app.voice.tokens import GeminiTokenMinter, VoiceNotConfiguredError, VoiceProviderError
from tests.conftest import SEED_TIME, Call, FakeMinter, FrozenClock

FAKE_KEY = "not-a-real-key-test-only-0123456789"

# ── Session initialisation ──────────────────────────────────────────────────


def test_create_session_returns_token_and_locked_config(voice_client: TestClient, minter: FakeMinter) -> None:
    r = voice_client.post("/api/voice/sessions")
    assert r.status_code == 201
    body = r.json()
    assert body["token"] == "auth_tokens/fake-1"
    assert body["model"] == "gemini-3.8-live"
    assert body["api_version"] == "v1beta"
    assert len(body["session_id"]) == 32 and len(body["session_secret"]) >= 40
    assert body["call_connected_cue"] == "[call connected]"
    # The browser gets exactly the config that was locked into the token.
    assert minter.calls[0]["config"] == body["live_config"]
    assert minter.calls[0]["model"] == "gemini-3.8-live"


def test_token_lifetimes(voice_client: TestClient, minter: FakeMinter) -> None:
    body = voice_client.post("/api/voice/sessions").json()
    assert minter.calls[0]["session_minutes"] == 15
    assert body["token_expires_at"] == (SEED_TIME + timedelta(minutes=15)).isoformat()
    assert body["new_session_expires_at"] == (SEED_TIME + timedelta(minutes=1)).isoformat()


def test_each_call_gets_its_own_session_and_token(voice_client: TestClient) -> None:
    a = voice_client.post("/api/voice/sessions").json()
    b = voice_client.post("/api/voice/sessions").json()
    assert a["session_id"] != b["session_id"]
    assert a["session_secret"] != b["session_secret"]
    assert a["token"] != b["token"]


def test_only_a_hash_of_the_session_secret_is_stored(voice_client: TestClient, db_path: Path) -> None:
    body = voice_client.post("/api/voice/sessions").json()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        stored = conn.execute("SELECT secret_sha256 FROM voice_sessions").fetchone()[0]
    assert body["session_secret"] not in stored
    assert len(stored) == 64


def test_live_config_contents() -> None:
    config = build_live_config(Settings(gemini_voice="Kore"))
    assert config["responseModalities"] == ["AUDIO"]
    assert config["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    assert config["inputAudioTranscription"] == {} and config["outputAudioTranscription"] == {}
    instruction = config["systemInstruction"]["parts"][0]["text"]
    for policy in (SHIPPING_POLICY, RETURN_POLICY, CANCELLATION_POLICY, COD_POLICY):
        assert policy in instruction  # verbatim
    assert "POLICY_UNSPECIFIED" in instruction and "exactly ₹499" in instruction
    assert "customer_confirmed true" in instruction


def test_every_tool_blocks_and_rejects_unknown_arguments() -> None:
    names = {t["name"] for t in TOOL_DECLARATIONS}
    assert names == {
        "get_order_details",
        "check_cancellation_eligibility",
        "cancel_order",
        "check_return_eligibility",
        "check_shipping",
        "check_cod",
    }
    for tool in TOOL_DECLARATIONS:
        assert tool["behavior"] == "BLOCKING", tool["name"]  # gemini-3.8-live defaults to NON_BLOCKING
        assert tool["parametersJsonSchema"]["additionalProperties"] is False


def test_live_config_is_valid_for_the_google_sdk() -> None:
    config = build_live_config(Settings())
    parsed = types.LiveConnectConfig.model_validate(config)
    assert parsed.model_dump(mode="json", by_alias=True, exclude_none=True) == config
    assert all(f.behavior == types.Behavior.BLOCKING for f in parsed.tools[0].function_declarations)  # type: ignore[index, union-attr]


# ── Failure handling ────────────────────────────────────────────────────────


def test_not_configured_without_api_key(settings: Settings, clock: FrozenClock, db_path: Path) -> None:
    assert settings.gemini_api_key is None
    with TestClient(create_app(settings, clock)) as c:  # default (real) minter factory
        r = c.post("/api/voice/sessions")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "VOICE_NOT_CONFIGURED"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM voice_sessions").fetchone()[0] == 0


def test_provider_failure_is_502_and_creates_no_session(settings: Settings, clock: FrozenClock, db_path: Path) -> None:
    failing = FakeMinter(fail=True)
    with TestClient(create_app(settings, clock, token_minter_factory=lambda: failing)) as c:
        r = c.post("/api/voice/sessions")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "VOICE_PROVIDER_ERROR"
    assert "FakeProviderDown" not in r.text
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM voice_sessions").fetchone()[0] == 0


def test_rate_limit_per_client(tmp_path: Path, clock: FrozenClock) -> None:
    s = Settings(database_path=tmp_path / "r.db", voice_sessions_per_ip_per_hour=2, log_level="ERROR")
    m = FakeMinter()
    with TestClient(create_app(s, clock, token_minter_factory=lambda: m)) as c:
        codes = [c.post("/api/voice/sessions").status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    assert len(m.calls) == 2  # the limited request never minted a token


# ── The real minter, with Google's client faked ─────────────────────────────


class _FakeGenaiClient:
    instances: ClassVar[list["_FakeGenaiClient"]] = []

    def __init__(self, *, api_key: str, http_options: types.HttpOptions) -> None:
        self.api_key = api_key
        self.http_options = http_options
        self.auth_tokens = self
        self.create_config: types.CreateAuthTokenConfig | None = None
        self.raise_with: Exception | None = None
        _FakeGenaiClient.instances.append(self)

    def create(self, *, config: types.CreateAuthTokenConfig) -> types.AuthToken:
        self.create_config = config
        if self.raise_with:
            raise self.raise_with
        return types.AuthToken(name="auth_tokens/real-shape")


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch) -> type[_FakeGenaiClient]:
    _FakeGenaiClient.instances.clear()
    monkeypatch.setattr("google.genai.Client", _FakeGenaiClient)
    return _FakeGenaiClient


def test_real_minter_locks_config_and_limits_uses(fake_genai: type[_FakeGenaiClient]) -> None:
    settings = Settings(gemini_api_key=FAKE_KEY, gemini_api_version="v1alpha")
    config = build_live_config(settings)
    token = GeminiTokenMinter(settings).mint(model="gemini-3.8-live", config=config, now=SEED_TIME, session_minutes=15)
    client = fake_genai.instances[0]
    assert token.name == "auth_tokens/real-shape"
    assert client.api_key == FAKE_KEY and client.http_options.api_version == "v1alpha"
    cfg = client.create_config
    assert cfg is not None
    assert cfg.uses == 1
    assert cfg.expire_time == SEED_TIME + timedelta(minutes=15)
    assert cfg.new_session_expire_time == SEED_TIME + timedelta(minutes=1)
    assert cfg.lock_additional_fields is None  # unset: the whole constrained config is locked
    assert cfg.live_connect_constraints is not None
    assert cfg.live_connect_constraints.model == "gemini-3.8-live"
    assert cfg.live_connect_constraints.config == types.LiveConnectConfig.model_validate(config)


def test_real_minter_hides_provider_error_text(
    fake_genai: type[_FakeGenaiClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    original_init = _FakeGenaiClient.__init__

    def failing_init(self: _FakeGenaiClient, **kw: Any) -> None:
        original_init(self, **kw)
        self.raise_with = RuntimeError(f"401 for key={FAKE_KEY}")

    monkeypatch.setattr(_FakeGenaiClient, "__init__", failing_init)
    with pytest.raises(VoiceProviderError) as exc:
        GeminiTokenMinter(Settings(gemini_api_key=FAKE_KEY)).mint(
            model="m", config=build_live_config(Settings()), now=SEED_TIME, session_minutes=15
        )
    assert FAKE_KEY not in str(exc.value) and exc.value.__cause__ is None


def test_real_minter_requires_key() -> None:
    with pytest.raises(VoiceNotConfiguredError):
        GeminiTokenMinter(Settings(gemini_api_key=None))


def test_api_key_never_appears_in_responses_or_logs(
    fake_genai: type[_FakeGenaiClient], tmp_path: Path, clock: FrozenClock
) -> None:
    settings = Settings(database_path=tmp_path / "k.db", gemini_api_key=FAKE_KEY, log_level="DEBUG")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    with TestClient(create_app(settings, clock)) as c:
        logging.getLogger("aura").addHandler(handler)
        try:
            created = c.post("/api/voice/sessions")
            call = Call(c, created.json())
            call.tool("get_order_details", order_id="ORD-101")
            ended = c.post(f"/api/voice/sessions/{call.id}/end", json={"transcript": []}, headers=call.headers)
            docs = c.get("/openapi.json")
        finally:
            logging.getLogger("aura").removeHandler(handler)
    assert created.status_code == 201 and fake_genai.instances[0].api_key == FAKE_KEY
    for text in (
        created.text,
        json.dumps(dict(created.headers)),
        ended.text,
        docs.text,
        stream.getvalue(),
        repr(settings),
        json.dumps(settings.model_dump(mode="json")),
    ):
        assert FAKE_KEY not in text


def test_api_key_setting_is_optional_and_masked() -> None:
    assert Settings().gemini_api_key is None
    assert Settings(gemini_api_key="   ").gemini_api_key is None
    assert str(Settings(gemini_api_key=FAKE_KEY).gemini_api_key) == "**********"


@pytest.mark.parametrize(
    "field,value", [("gemini_voice", "Robot"), ("gemini_api_version", "v2"), ("voice_session_minutes", 16)]
)
def test_invalid_voice_settings_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})


def test_cors_allows_session_secret_header(voice_client: TestClient) -> None:
    r = voice_client.options(
        "/api/voice/sessions/x/end",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-session-secret",
        },
    )
    assert r.status_code == 200
    assert "x-session-secret" in r.headers["access-control-allow-headers"].lower()


def test_start_call_helper_works(start_call: Callable[[], Call]) -> None:
    assert start_call().id

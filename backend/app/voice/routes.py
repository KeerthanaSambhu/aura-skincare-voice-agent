"""HTTP routes for voice calls.

POST /api/voice/sessions                         start a call: mint a token, create a session
POST /api/voice/sessions/{id}/tool-calls         run a tool the model asked for
POST /api/voice/sessions/{id}/end                end the call: store transcript, build summary

The tool-call and end routes need the X-Session-Secret header returned when the
session was created, so one browser can't act on another browser's call.
"""

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from ..clock import Clock
from ..config import Settings
from ..errors import AppError
from .prompt import CALL_CONNECTED_CUE, build_live_config
from .summary import build_summary
from .tokens import GeminiTokenMinter, TokenMinter, VoiceNotConfiguredError, VoiceProviderError
from .tools import execute_tool

logger = logging.getLogger("aura.voice")

# Tool calls and the end call are accepted a little after the token expires,
# so a call ending right at the limit can still be closed and summarised.
SESSION_GRACE = timedelta(minutes=5)


# ── Request and response models ─────────────────────────────────────────────
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolCallRequest(_Strict):
    call_id: str = Field(min_length=1, max_length=128, description="The function call id from Gemini's toolCall.")
    name: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class TranscriptTurn(_Strict):
    speaker: Literal["customer", "agent"]
    text: str = Field(min_length=1, max_length=4000)


class EndCallRequest(_Strict):
    transcript: list[TranscriptTurn] = Field(default_factory=list, max_length=400)
    end_reason: Literal["customer_ended", "disconnected", "error", "timeout"] = "customer_ended"
    # Tool calls that never reached this server (e.g. network down), counted by the browser.
    client_tool_failures: int = Field(default=0, ge=0, le=100)


class SessionCreated(BaseModel):
    session_id: str
    session_secret: str = Field(description="Send as X-Session-Secret on tool-call and end requests.")
    token: str = Field(description="Single-use Gemini ephemeral token. Valid to connect for 1 minute.")
    token_expires_at: str
    new_session_expires_at: str
    model: str
    api_version: str
    live_config: dict[str, Any] = Field(description="Pass unchanged to ai.live.connect; it is locked into the token.")
    call_connected_cue: str


class ToolCallResponse(BaseModel):
    call_id: str
    name: str
    response: dict[str, Any] = Field(description="Send unchanged to the model as the function response.")


class EndCallResponse(BaseModel):
    session_id: str
    transcript: list[dict[str, str]]
    summary: dict[str, Any]


# ── Rate limiting ───────────────────────────────────────────────────────────
class SessionRateLimiter:
    """Per-client sliding window. In memory: resets on restart, per server process."""

    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 3600:
                hits.popleft()
            if len(hits) >= self.per_hour:
                return False
            hits.append(now)
            return True


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def build_voice_router(
    settings: Settings,
    clock_getter: Callable[[], Clock],
    conn_dependency: Callable[[], Iterator[sqlite3.Connection]],
    minter_factory: Callable[[], TokenMinter],
) -> APIRouter:
    router = APIRouter(prefix="/api/voice", tags=["voice"])
    limiter = SessionRateLimiter(settings.voice_sessions_per_ip_per_hour)
    Conn = Annotated[sqlite3.Connection, Depends(conn_dependency)]
    Secret = Annotated[str | None, Header(alias="X-Session-Secret", max_length=128)]

    def now() -> datetime:
        return clock_getter()()

    def load_session(conn: sqlite3.Connection, session_id: str, secret: str | None) -> sqlite3.Row:
        row: sqlite3.Row | None = None
        if len(session_id) <= 64:
            row = conn.execute("SELECT * FROM voice_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise AppError("SESSION_NOT_FOUND", "That voice session doesn't exist.", 404)
        if not secret or not hmac.compare_digest(row["secret_sha256"], _hash(secret)):
            raise AppError("SESSION_FORBIDDEN", "Missing or wrong session secret.", 403)
        return row

    def session_open(row: sqlite3.Row) -> bool:
        return now() <= datetime.fromisoformat(row["token_expires_at"]) + SESSION_GRACE

    @router.post("/sessions", status_code=201, response_model=SessionCreated, summary="Start a voice call")
    def create_session(request: Request, conn: Conn) -> Any:
        client = request.client.host if request.client else "unknown"
        try:
            minter = minter_factory()
        except VoiceNotConfiguredError:
            raise AppError(
                "VOICE_NOT_CONFIGURED", "Voice calling isn't set up on this server yet (no Gemini API key).", 503
            ) from None
        if not limiter.allow(client):
            raise AppError("RATE_LIMITED", "Too many calls started from this device. Please wait and try again.", 429)

        started = now()
        live_config = build_live_config(settings)
        try:
            token = minter.mint(
                model=settings.gemini_live_model,
                config=live_config,
                now=started,
                session_minutes=settings.voice_session_minutes,
            )
        except VoiceProviderError as exc:
            logger.error("voice_token_mint_failed", extra={"error_type": str(exc)})
            raise AppError(
                "VOICE_PROVIDER_ERROR", "Couldn't start a voice session with the voice provider. Please try again.", 502
            ) from None

        session_id = uuid.uuid4().hex
        session_secret = secrets.token_urlsafe(32)
        conn.execute(
            """INSERT INTO voice_sessions (session_id, secret_sha256, status, created_at, token_expires_at)
               VALUES (?, ?, 'active', ?, ?)""",
            (session_id, _hash(session_secret), started.isoformat(), token.expires_at.isoformat()),
        )
        logger.info("voice_session_created", extra={"session_id": session_id, "model": settings.gemini_live_model})
        return {
            "session_id": session_id,
            "session_secret": session_secret,
            "token": token.name,
            "token_expires_at": token.expires_at.isoformat(),
            "new_session_expires_at": token.new_session_expires_at.isoformat(),
            "model": settings.gemini_live_model,
            "api_version": settings.gemini_api_version,
            "live_config": live_config,
            "call_connected_cue": CALL_CONNECTED_CUE,
        }

    @router.post(
        "/sessions/{session_id}/tool-calls", response_model=ToolCallResponse, summary="Run a tool Aria requested"
    )
    def tool_call(session_id: str, body: ToolCallRequest, conn: Conn, x_session_secret: Secret = None) -> Any:
        row = load_session(conn, session_id, x_session_secret)
        if row["status"] != "active":
            raise AppError("SESSION_ENDED", "This call has already ended.", 409)
        if not session_open(row):
            raise AppError("SESSION_EXPIRED", "This call's time limit has passed.", 409)
        response = execute_tool(
            conn,
            session_id=session_id,
            call_id=body.call_id,
            name=body.name,
            args=body.args,
            now=now(),
            tz=settings.tz,
        )
        return {"call_id": body.call_id, "name": body.name, "response": response}

    @router.post("/sessions/{session_id}/end", response_model=EndCallResponse, summary="End a call and summarise it")
    def end_call(session_id: str, body: EndCallRequest, conn: Conn, x_session_secret: Secret = None) -> Any:
        row = load_session(conn, session_id, x_session_secret)
        if row["status"] == "ended":
            # Idempotent: a retried end request gets the stored record, never a new one.
            return stored_record(conn, session_id)

        ended_at = now()
        transcript = [t.model_dump() for t in body.transcript]
        tool_rows = conn.execute(
            "SELECT * FROM voice_tool_calls WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        summary = build_summary(
            session=row,
            tool_rows=tool_rows,
            transcript=transcript,
            client_tool_failures=body.client_tool_failures,
            ended_at=ended_at,
            end_reason=body.end_reason,
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                "UPDATE voice_sessions SET status = 'ended', ended_at = ?, end_reason = ? "
                "WHERE session_id = ? AND status = 'active'",
                (ended_at.isoformat(), body.end_reason, session_id),
            ).rowcount
            if updated != 1:  # another request ended it first
                conn.execute("ROLLBACK")
                return stored_record(conn, session_id)
            conn.executemany(
                "INSERT INTO voice_transcript_turns (session_id, seq, speaker, text) VALUES (?, ?, ?, ?)",
                [(session_id, i, t["speaker"], t["text"]) for i, t in enumerate(transcript)],
            )
            conn.execute(
                "INSERT INTO voice_summaries (session_id, summary_json) VALUES (?, ?)",
                (session_id, json.dumps(summary, ensure_ascii=False)),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        logger.info(
            "voice_session_ended",
            extra={"session_id": session_id, "end_reason": body.end_reason, "turns": len(transcript)},
        )
        return {"session_id": session_id, "transcript": transcript, "summary": summary}

    def stored_record(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
        turns = conn.execute(
            "SELECT speaker, text FROM voice_transcript_turns WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
        summary_row = conn.execute(
            "SELECT summary_json FROM voice_summaries WHERE session_id = ?", (session_id,)
        ).fetchone()
        return {
            "session_id": session_id,
            "transcript": [{"speaker": t["speaker"], "text": t["text"]} for t in turns],
            "summary": json.loads(summary_row["summary_json"]) if summary_row else {},
        }

    return router


def default_minter_factory(settings: Settings) -> Callable[[], TokenMinter]:
    def factory() -> TokenMinter:
        return GeminiTokenMinter(settings)

    return factory

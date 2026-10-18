"""Executes the tools Aria asks for, using the same Phase 3 functions as the REST API.

Every call returns a JSON object for the model:
    {"ok": true,  "result": {...}}                     the tool ran
    {"ok": false, "error": {"code": ..., "message": ...}}  it didn't, and why

Nothing here raises to the model. Bad arguments, unknown orders and database
errors all become ok:false results, so the model always learns that a lookup
failed instead of being left to guess.

Cancellation has two server-side gates on top of cancel_order's own checks:
1. customer_confirmed must be true, and
2. check_cancellation_eligibility must have returned ELIGIBLE for the same
   order earlier in this same call.
"""

import json
import logging
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..cancellation import cancel_order
from ..errors import AppError
from ..order_ids import normalize_order_id
from ..orders import fetch_order_row, get_order_details
from ..policies import check_cancellation, check_cod, check_return, check_shipping

logger = logging.getLogger("aura.voice.tools")

MAX_ARGS_BYTES = 2048


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderArgs(_Args):
    order_id: str = Field(max_length=64)


# Booleans are strict: only JSON true/false count. In Pydantic's default lax mode
# the string "yes" would become True, which must never count as confirmation.
class CancelArgs(OrderArgs):
    customer_confirmed: bool = Field(strict=True)


class ReturnArgs(OrderArgs):
    reason: Literal["unwanted", "damaged", "defective"] | None = None
    opened: bool | None = Field(default=None, strict=True)
    has_photos: bool | None = Field(default=None, strict=True)


class ValueArgs(_Args):
    order_value: Decimal | None = Field(default=None, gt=0, le=10_000_000, max_digits=10, decimal_places=2)
    order_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _exactly_one(self) -> "ValueArgs":
        if (self.order_value is None) == (self.order_id is None):
            raise ValueError("give exactly one of order_value or order_id")
        return self


ARG_MODELS: dict[str, type[_Args]] = {
    "get_order_details": OrderArgs,
    "check_cancellation_eligibility": OrderArgs,
    "cancel_order": CancelArgs,
    "check_return_eligibility": ReturnArgs,
    "check_shipping": ValueArgs,
    "check_cod": ValueArgs,
}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _cancellation_confirmed_eligible(conn: sqlite3.Connection, session_id: str, order_id: str) -> bool:
    row = conn.execute(
        """SELECT 1 FROM voice_tool_calls
           WHERE session_id = ? AND name = 'check_cancellation_eligibility'
             AND ok = 1 AND order_id = ? AND outcome = 'ELIGIBLE' LIMIT 1""",
        (session_id, order_id),
    ).fetchone()
    return row is not None


def _run(
    conn: sqlite3.Connection, session_id: str, name: str, args: _Args, now: datetime, tz: ZoneInfo
) -> tuple[dict[str, Any], str | None, str | None]:
    """Execute a validated tool. Returns (response, order_id, outcome)."""
    if isinstance(args, CancelArgs):
        order_id = normalize_order_id(args.order_id)
        if not args.customer_confirmed:
            return (
                _error(
                    "CONFIRMATION_REQUIRED",
                    f"Not cancelled. Ask the customer to confirm they want to cancel {order_id}, "
                    "then call cancel_order with customer_confirmed true.",
                ),
                order_id,
                "CONFIRMATION_REQUIRED",
            )
        if not _cancellation_confirmed_eligible(conn, session_id, order_id):
            return (
                _error(
                    "ELIGIBILITY_NOT_CHECKED",
                    f"Not cancelled. Call check_cancellation_eligibility for {order_id} first; cancel only if it is "
                    "ELIGIBLE and the customer confirms.",
                ),
                order_id,
                "ELIGIBILITY_NOT_CHECKED",
            )
        result = cancel_order(conn, order_id, now)
        return {"ok": True, "result": result.to_dict()}, order_id, result.outcome

    if name == "get_order_details":
        assert isinstance(args, OrderArgs)
        details = get_order_details(conn, args.order_id, now, tz)
        return {"ok": True, "result": details}, details["order_id"], details["status"]

    if name == "check_cancellation_eligibility":
        assert isinstance(args, OrderArgs)
        policy = check_cancellation(fetch_order_row(conn, normalize_order_id(args.order_id)))
    elif isinstance(args, ReturnArgs):
        order = fetch_order_row(conn, normalize_order_id(args.order_id))
        policy = check_return(order, args.opened, args.reason, now, args.has_photos)
    else:
        assert isinstance(args, ValueArgs)
        if args.order_id is not None:
            oid = normalize_order_id(args.order_id)
            value: Decimal = Decimal(fetch_order_row(conn, oid)["value_inr"])
        else:
            assert args.order_value is not None
            oid, value = None, args.order_value
        policy = check_shipping(value, oid) if name == "check_shipping" else check_cod(value, oid)
    return {"ok": True, "result": policy.to_dict()}, policy.order_id, policy.outcome


def execute_tool(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    call_id: str,
    name: str,
    args: dict[str, Any],
    now: datetime,
    tz: ZoneInfo,
) -> dict[str, Any]:
    """Validate, run and record one tool call. Always returns a model-facing response."""
    order_id: str | None = None
    outcome: str | None = None
    try:
        model = ARG_MODELS.get(name)
        if model is None:
            response = _error("UNKNOWN_TOOL", f"There is no tool called {name}.")
        elif len(json.dumps(args)) > MAX_ARGS_BYTES:
            response = _error("INVALID_ARGUMENTS", "Tool arguments are too large.")
        else:
            try:
                parsed = model.model_validate(args)
            except ValidationError as exc:
                fields = sorted({".".join(str(p) for p in e["loc"]) or "arguments" for e in exc.errors()})
                response = _error("INVALID_ARGUMENTS", f"Invalid arguments for {name}: check {', '.join(fields)}.")
            else:
                response, order_id, outcome = _run(conn, session_id, name, parsed, now, tz)
    except AppError as exc:
        response = _error(exc.code, exc.message)
        order_id = exc.order_id
        outcome = exc.code
    except sqlite3.Error:
        logger.error("tool_database_error", extra={"tool": name, "session_id": session_id})
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        response = _error("DATABASE_UNAVAILABLE", "Order records are unavailable right now. Nothing was changed.")
        outcome = "DATABASE_UNAVAILABLE"

    if not response["ok"] and outcome is None:
        outcome = response["error"]["code"]
    record_tool_call(conn, session_id, call_id, name, args, response, order_id, outcome, now)
    logger.info(
        "voice_tool_call",
        extra={"session_id": session_id, "tool": name, "ok": response["ok"], "order_id": order_id, "outcome": outcome},
    )
    return response


def record_tool_call(
    conn: sqlite3.Connection,
    session_id: str,
    call_id: str,
    name: str,
    args: dict[str, Any],
    response: dict[str, Any],
    order_id: str | None,
    outcome: str | None,
    now: datetime,
) -> None:
    try:
        conn.execute(
            """INSERT INTO voice_tool_calls
               (session_id, call_id, name, args_json, ok, order_id, outcome, result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                call_id,
                name,
                json.dumps(args, default=str)[:MAX_ARGS_BYTES],
                1 if response["ok"] else 0,
                order_id,
                outcome,
                json.dumps(response, default=str, ensure_ascii=False),
                now.isoformat(),
            ),
        )
    except sqlite3.Error:
        # The tool already ran; losing the audit row must not change what the model is told.
        logger.error("tool_call_not_recorded", extra={"tool": name, "session_id": session_id})

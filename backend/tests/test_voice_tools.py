"""Phase 4: the tool gateway the voice model uses."""

import sqlite3
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Call, FrozenClock

# ── Successful order tools ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,oid,status",
    [
        ("ORD-101", "ORD-101", "Out for Delivery"),
        ("ord 102", "ORD-102", "Delivered"),
        ("Order 103", "ORD-103", "Processing"),
    ],
)
def test_get_order_details(start_call: Callable[[], Call], raw: str, oid: str, status: str) -> None:
    r = start_call().tool("get_order_details", order_id=raw)
    assert r["ok"] is True
    assert (r["result"]["order_id"], r["result"]["status"]) == (oid, status)
    assert "no live carrier tracking" in r["result"]["data_note"]


def test_ord_101_fixed_estimate_through_the_tool(start_call: Callable[[], Call], clock: FrozenClock) -> None:
    clock.advance(hours=12)  # 22:00 IST
    timing = start_call().tool("get_order_details", order_id="ORD-101")["result"]["timing"]
    assert timing["summary"] == "Expected by 6 PM today"


# ── Unsuccessful tools: always ok:false, never invented data ────────────────


@pytest.mark.parametrize(
    "raw,code", [("ORD-999", "ORDER_NOT_FOUND"), ("ORD-1O1", "ORDER_ID_INVALID"), ("  ", "ORDER_ID_MISSING")]
)
def test_order_errors_are_structured(start_call: Callable[[], Call], raw: str, code: str) -> None:
    r = start_call().tool("get_order_details", order_id=raw)
    assert r == {"ok": False, "error": {"code": code, "message": r["error"]["message"]}}
    assert "result" not in r


@pytest.mark.parametrize(
    "name,args,detail",
    [
        ("get_order_details", {}, "order_id"),
        ("get_order_details", {"order_id": 101}, "order_id"),
        ("get_order_details", {"order_id": "ORD-101", "customer_name": "x"}, "customer_name"),
        ("check_return_eligibility", {"order_id": "ORD-102", "reason": "changed mind"}, "reason"),
        ("check_shipping", {}, "arguments"),
        ("check_shipping", {"order_value": 699, "order_id": "ORD-101"}, "arguments"),
        ("check_shipping", {"order_value": -1}, "order_value"),
        ("cancel_order", {"order_id": "ORD-103"}, "customer_confirmed"),
        ("cancel_order", {"order_id": "ORD-103", "customer_confirmed": "yes"}, "customer_confirmed"),
        ("cancel_order", {"order_id": "ORD-103", "customer_confirmed": 1}, "customer_confirmed"),
        ("cancel_order", {"order_id": "ORD-103", "customer_confirmed": "true"}, "customer_confirmed"),
        ("check_return_eligibility", {"order_id": "ORD-102", "reason": "unwanted", "opened": "no"}, "opened"),
    ],
)
def test_malformed_arguments(start_call: Callable[[], Call], name: str, args: dict[str, Any], detail: str) -> None:
    r = start_call().tool(name, **args)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENTS"
    assert detail in r["error"]["message"]


def test_unknown_tool(start_call: Callable[[], Call]) -> None:
    r = start_call().tool("refund_order", order_id="ORD-102")
    assert r["error"]["code"] == "UNKNOWN_TOOL"


def test_oversized_arguments(start_call: Callable[[], Call]) -> None:
    r = start_call().tool("get_order_details", order_id="ORD-101", junk="x" * 3000)
    assert r["error"]["code"] == "INVALID_ARGUMENTS"


def test_database_failure_is_reported_not_hidden(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    conn.execute("ALTER TABLE orders RENAME TO orders_gone")
    r = call.tool("get_order_details", order_id="ORD-101")
    assert r["ok"] is False and r["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "orders_gone" not in r["error"]["message"]


def test_tool_calls_are_recorded_against_their_session(
    start_call: Callable[[], Call], conn: sqlite3.Connection
) -> None:
    a, b = start_call(), start_call()
    a.tool("get_order_details", order_id="ORD-101")
    b.tool("get_order_details", order_id="ORD-999")
    rows = conn.execute("SELECT session_id, name, ok, order_id, outcome FROM voice_tool_calls ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        (a.id, "get_order_details", 1, "ORD-101", "Out for Delivery"),
        (b.id, "get_order_details", 0, "ORD-999", "ORDER_NOT_FOUND"),
    ]


# ── Policies through the tools ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,outcome,fee",
    [
        (450, "NOT_ELIGIBLE", 50),
        (498.99, "NOT_ELIGIBLE", 50),
        (499, "POLICY_UNSPECIFIED", None),
        (499.0, "POLICY_UNSPECIFIED", None),
        (499.01, "ELIGIBLE", 0),
        (699, "ELIGIBLE", 0),
    ],
)
def test_shipping_boundary(start_call: Callable[[], Call], value: float, outcome: str, fee: int | None) -> None:
    r = start_call().tool("check_shipping", order_value=value)
    assert r["result"]["outcome"] == outcome
    assert r["result"]["details"]["shipping_fee_inr"] == fee


def test_shipping_for_ord_102_is_unspecified(start_call: Callable[[], Call]) -> None:
    r = start_call().tool("check_shipping", order_id="ORD-102")
    assert (r["result"]["outcome"], r["result"]["eligible"]) == ("POLICY_UNSPECIFIED", None)


@pytest.mark.parametrize("value,eligible", [(2500, True), (2500.01, False)])
def test_cod(start_call: Callable[[], Call], value: float, eligible: bool) -> None:
    assert start_call().tool("check_cod", order_value=value)["result"]["eligible"] is eligible


def test_returns(start_call: Callable[[], Call]) -> None:
    call = start_call()
    assert (
        call.tool("check_return_eligibility", order_id="ORD-102", reason="unwanted", opened=True)["result"][
            "reason_code"
        ]
        == "OUTSIDE_RETURN_WINDOW"
    )
    assert (
        call.tool("check_return_eligibility", order_id="ORD-102", reason="damaged", has_photos=True)["result"][
            "reason_code"
        ]
        == "OUTSIDE_DAMAGE_WINDOW"
    )
    assert (
        call.tool("check_return_eligibility", order_id="ORD-101", reason="unwanted")["result"]["reason_code"]
        == "NOT_DELIVERED"
    )


# ── Cancellation: confirmation and eligibility gates ────────────────────────


def status(conn: sqlite3.Connection, oid: str) -> str:
    return str(conn.execute("SELECT status FROM orders WHERE order_id = ?", (oid,)).fetchone()[0])


def test_cancel_without_confirmation_is_refused(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    call.tool("check_cancellation_eligibility", order_id="ORD-103")
    r = call.tool("cancel_order", order_id="ORD-103", customer_confirmed=False)
    assert r["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert status(conn, "ORD-103") == "Processing"


def test_cancel_without_eligibility_check_is_refused(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    r = start_call().tool("cancel_order", order_id="ORD-103", customer_confirmed=True)
    assert r["error"]["code"] == "ELIGIBILITY_NOT_CHECKED"
    assert status(conn, "ORD-103") == "Processing"


def test_eligibility_from_another_session_does_not_count(
    start_call: Callable[[], Call], conn: sqlite3.Connection
) -> None:
    other, call = start_call(), start_call()
    assert other.tool("check_cancellation_eligibility", order_id="ORD-103")["result"]["eligible"] is True
    r = call.tool("cancel_order", order_id="ORD-103", customer_confirmed=True)
    assert r["error"]["code"] == "ELIGIBILITY_NOT_CHECKED"
    assert status(conn, "ORD-103") == "Processing"


def test_eligibility_for_another_order_does_not_count(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    call.tool("check_cancellation_eligibility", order_id="ORD-103")
    r = call.tool("cancel_order", order_id="ORD-101", customer_confirmed=True)
    assert r["error"]["code"] == "ELIGIBILITY_NOT_CHECKED"
    assert status(conn, "ORD-101") == "Out for Delivery"


def test_confirmed_cancel_of_ord_103(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    assert call.tool("check_cancellation_eligibility", order_id="ord 103")["result"]["outcome"] == "ELIGIBLE"
    r = call.tool("cancel_order", order_id="ORD-103", customer_confirmed=True)
    assert r["ok"] is True
    assert (r["result"]["cancelled"], r["result"]["outcome"]) == (True, "CANCELLED")
    assert status(conn, "ORD-103") == "Cancelled"
    again = call.tool("cancel_order", order_id="ORD-103", customer_confirmed=True)
    assert (again["result"]["cancelled"], again["result"]["outcome"]) == (False, "ALREADY_CANCELLED")


def test_ord_101_cannot_be_cancelled_even_if_confirmed(
    start_call: Callable[[], Call], conn: sqlite3.Connection
) -> None:
    call = start_call()
    assert call.tool("check_cancellation_eligibility", order_id="ORD-101")["result"]["outcome"] == "NOT_ELIGIBLE"
    r = call.tool("cancel_order", order_id="ORD-101", customer_confirmed=True)
    assert r["error"]["code"] == "ELIGIBILITY_NOT_CHECKED"
    assert status(conn, "ORD-101") == "Out for Delivery"


def test_status_change_after_eligibility_check_is_caught(
    start_call: Callable[[], Call], conn: sqlite3.Connection
) -> None:
    """Eligibility was ELIGIBLE, but the order shipped before the customer confirmed."""
    call = start_call()
    call.tool("check_cancellation_eligibility", order_id="ORD-103")
    conn.execute("UPDATE orders SET status = 'Shipped' WHERE order_id = 'ORD-103'")
    r = call.tool("cancel_order", order_id="ORD-103", customer_confirmed=True)
    assert (r["result"]["cancelled"], r["result"]["outcome"]) == (False, "NOT_ELIGIBLE")
    assert status(conn, "ORD-103") == "Shipped"


# ── Session access ──────────────────────────────────────────────────────────


def post_tool(client: TestClient, session_id: str, headers: dict[str, str]) -> Any:
    return client.post(
        f"/api/voice/sessions/{session_id}/tool-calls",
        json={"call_id": "x", "name": "get_order_details", "args": {"order_id": "ORD-101"}},
        headers=headers,
    )


def test_wrong_or_missing_secret(start_call: Callable[[], Call], voice_client: TestClient) -> None:
    call = start_call()
    assert post_tool(voice_client, call.id, {"X-Session-Secret": "nope"}).status_code == 403
    assert post_tool(voice_client, call.id, {}).status_code == 403
    other = start_call()
    assert post_tool(voice_client, call.id, other.headers).status_code == 403  # another call's secret


def test_unknown_session(voice_client: TestClient) -> None:
    r = post_tool(voice_client, "0" * 32, {"X-Session-Secret": "x"})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "SESSION_NOT_FOUND")


def test_tools_rejected_after_end(start_call: Callable[[], Call], voice_client: TestClient) -> None:
    call = start_call()
    call.end()
    r = post_tool(voice_client, call.id, call.headers)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "SESSION_ENDED")


def test_tools_rejected_after_expiry(
    start_call: Callable[[], Call], voice_client: TestClient, clock: FrozenClock
) -> None:
    call = start_call()
    clock.advance(minutes=15 + 5, seconds=1)  # token lifetime + grace
    r = post_tool(voice_client, call.id, call.headers)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "SESSION_EXPIRED")


def test_tools_allowed_within_grace(
    start_call: Callable[[], Call], voice_client: TestClient, clock: FrozenClock
) -> None:
    call = start_call()
    clock.now += timedelta(minutes=19)
    assert post_tool(voice_client, call.id, call.headers).status_code == 200


@pytest.mark.parametrize(
    "body",
    [{"call_id": "", "name": "x", "args": {}}, {"name": "x"}, {"call_id": "c", "name": "x", "args": [], "extra": 1}],
)
def test_tool_request_validation(
    start_call: Callable[[], Call], voice_client: TestClient, body: dict[str, Any]
) -> None:
    call = start_call()
    r = voice_client.post(f"/api/voice/sessions/{call.id}/tool-calls", json=body, headers=call.headers)
    assert r.status_code == 422

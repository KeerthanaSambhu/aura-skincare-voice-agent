"""Phase 4: ending calls, transcripts, and the structured summary."""

import json
import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Call, FrozenClock

REQUIRED_KEYS = {
    "session_id",
    "started_at",
    "ended_at",
    "duration_seconds",
    "customer_intent",
    "customer_issue",
    "order_id",
    "order_ids",
    "actions_taken",
    "resolution_status",
    "final_outcome",
    "follow_up_required",
    "follow_up_reasons",
    "unresolved_issues",
    "call_summary",
    "summary_source",
}


def test_order_tracking_call(start_call: Callable[[], Call], clock: FrozenClock) -> None:
    call = start_call()
    call.tool("get_order_details", order_id="ORD-101")
    clock.advance(seconds=95)
    out = call.end(
        [
            ("agent", "Hi, I'm Aria from Aura Skincare."),
            ("customer", "Where is my order ORD-101?"),
            ("agent", "It's out for delivery and expected by 6 PM today."),
        ]
    )
    s = out["summary"]
    assert set(s) >= REQUIRED_KEYS
    assert s["customer_intent"] == "ORDER_TRACKING"
    assert s["customer_issue"] == "Where is my order ORD-101?"  # verbatim
    assert s["order_id"] == "ORD-101"
    assert s["resolution_status"] == "RESOLVED" and s["follow_up_required"] is False
    assert s["duration_seconds"] == 95
    assert [a["tool"] for a in s["actions_taken"]] == ["get_order_details"]
    assert "Looked up ORD-101: Out for Delivery, Expected by 6 PM today." in s["call_summary"]
    assert json.loads(json.dumps(s)) == s  # valid JSON


def test_transcript_is_kept_in_order(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    turns = [("agent", "Hello"), ("customer", "Hi"), ("agent", "How can I help?"), ("customer", "Bye")]
    out = call.end(turns)
    assert [(t["speaker"], t["text"]) for t in out["transcript"]] == turns
    rows = conn.execute(
        "SELECT seq, speaker, text FROM voice_transcript_turns WHERE session_id = ? ORDER BY seq", (call.id,)
    ).fetchall()
    assert [(r["speaker"], r["text"]) for r in rows] == turns


def test_cancellation_call(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("check_cancellation_eligibility", order_id="ORD-103")
    call.tool("cancel_order", order_id="ORD-103", customer_confirmed=True)
    s = call.end([("customer", "Please cancel ORD-103"), ("customer", "Yes, cancel it")])["summary"]
    assert (s["customer_intent"], s["order_id"], s["resolution_status"]) == ("CANCELLATION", "ORD-103", "RESOLVED")
    assert s["final_outcome"].startswith("Order cancelled")
    assert any(a.get("cancelled") for a in s["actions_taken"])


def test_unconfirmed_cancel_is_not_reported_as_cancelled(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("check_cancellation_eligibility", order_id="ORD-103")
    call.tool("cancel_order", order_id="ORD-103", customer_confirmed=False)
    s = call.end([("customer", "Can I cancel ORD-103?")])["summary"]
    assert "cancelled" not in s["final_outcome"].lower()
    assert not any(a.get("cancelled") for a in s["actions_taken"])


def test_policy_declined_return(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("check_return_eligibility", order_id="ORD-102", reason="unwanted", opened=True)
    s = call.end([("customer", "I opened ORD-102 and want to return it")])["summary"]
    assert (s["customer_intent"], s["resolution_status"]) == ("RETURN_REFUND", "POLICY_DECLINED")
    assert s["follow_up_required"] is False


def test_499_shipping_needs_follow_up(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("check_shipping", order_value=499)
    s = call.end([("customer", "Is shipping free on a 499 rupee order?")])["summary"]
    assert (s["customer_intent"], s["resolution_status"]) == ("SHIPPING_QUESTION", "NEEDS_FOLLOW_UP")
    assert s["follow_up_required"] is True
    assert "doesn't specify" in s["follow_up_reasons"][0]
    assert s["order_id"] is None


def test_failed_lookup_after_a_successful_one_is_unresolved(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("get_order_details", order_id="ORD-101")
    call.tool("get_order_details", order_id="ORD-999")
    s = call.end([("customer", "ORD-101, and also ORD-999")])["summary"]
    assert s["resolution_status"] == "NOT_DETERMINED"
    assert "ORD-999" in s["unresolved_issues"][0]


def test_unknown_order_is_unresolved(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("get_order_details", order_id="ORD-999")
    s = call.end([("customer", "Where is ORD-999?")])["summary"]
    assert s["order_id"] is None  # never an ID that wasn't found
    assert s["resolution_status"] == "NOT_DETERMINED" and s["follow_up_required"] is True
    assert "ORD-999" in s["unresolved_issues"][0]


def test_unknown_then_corrected_order_is_resolved(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("get_order_details", order_id="ORD-999")
    call.tool("get_order_details", order_id="ORD-101")
    s = call.end([("customer", "Where is ORD-999? Sorry, ORD-101")])["summary"]
    assert (s["order_id"], s["resolution_status"]) == ("ORD-101", "RESOLVED")
    assert s["unresolved_issues"] == []  # treated as a corrected number


def test_needs_info_is_unresolved(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE orders SET delivered_at = ? WHERE order_id = 'ORD-102'", ("2026-10-16T04:30:00+00:00",))
    call = start_call()
    r = call.tool("check_return_eligibility", order_id="ORD-102", reason="unwanted")
    assert r["result"]["outcome"] == "NEEDS_INFO"
    s = call.end([("customer", "I want to return ORD-102")])["summary"]
    assert s["resolution_status"] == "NOT_DETERMINED" and "OPENED_UNKNOWN" in s["unresolved_issues"][0]


def test_out_of_scope_conversation_without_tools(start_call: Callable[[], Call]) -> None:
    s = start_call().end(
        [
            ("customer", "Can you book me a flight to Goa?"),
            ("agent", "Sorry, I can only help with Aura Skincare queries."),
        ]
    )["summary"]
    assert s["customer_intent"] == "GENERAL_INQUIRY"
    assert s["resolution_status"] == "NOT_DETERMINED"  # nothing on record proves an outcome
    assert s["order_id"] is None and s["actions_taken"] == []
    assert s["customer_issue"] == "Can you book me a flight to Goa?"
    assert "No order or policy tool was used" in s["call_summary"]


def test_empty_call(start_call: Callable[[], Call]) -> None:
    s = start_call().end([("agent", "Hi, I'm Aria.")])["summary"]
    assert (s["customer_intent"], s["resolution_status"], s["customer_issue"]) == (
        "NO_CONVERSATION",
        "NO_CONVERSATION",
        None,
    )


def test_tool_failures_need_follow_up(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    conn.execute("ALTER TABLE orders RENAME TO orders_gone")
    call.tool("get_order_details", order_id="ORD-101")
    s = call.end([("customer", "Where is ORD-101?")])["summary"]
    assert s["resolution_status"] == "NEEDS_FOLLOW_UP" and s["order_id"] is None


def test_client_side_tool_failures_need_follow_up(start_call: Callable[[], Call]) -> None:
    s = start_call().end([("customer", "Where is ORD-101?")], client_tool_failures=2, end_reason="disconnected")[
        "summary"
    ]
    assert s["resolution_status"] == "NEEDS_FOLLOW_UP"
    assert "2 tool call(s) failed" in s["follow_up_reasons"][0]


@pytest.mark.parametrize("reason", ["disconnected", "timeout", "error"])
def test_unexpected_end_is_not_reported_as_resolved(start_call: Callable[[], Call], reason: str) -> None:
    call = start_call()
    call.tool("get_order_details", order_id="ORD-102")
    s = call.end([("customer", "Where is ORD-102?")], end_reason=reason)["summary"]
    assert s["end_reason"] == reason
    assert s["resolution_status"] == "NEEDS_FOLLOW_UP" and s["follow_up_required"] is True
    assert "ended unexpectedly" in s["follow_up_reasons"][-1]


def test_customer_ended_call_is_resolved_and_records_reason(start_call: Callable[[], Call]) -> None:
    call = start_call()
    call.tool("get_order_details", order_id="ORD-102")
    s = call.end([("customer", "Where is ORD-102?")])["summary"]
    assert (s["end_reason"], s["resolution_status"], s["follow_up_required"]) == ("customer_ended", "RESOLVED", False)


def test_unexpected_end_without_conversation_stays_no_conversation(start_call: Callable[[], Call]) -> None:
    s = start_call().end([], end_reason="timeout")["summary"]
    assert (s["resolution_status"], s["follow_up_required"]) == ("NO_CONVERSATION", False)


def test_end_is_idempotent(start_call: Callable[[], Call]) -> None:
    call = start_call()
    first = call.end([("customer", "Hello")])
    second = call.end([("customer", "A different transcript")])
    assert second == first


def test_sessions_are_kept_separate(start_call: Callable[[], Call]) -> None:
    a, b = start_call(), start_call()
    a.tool("get_order_details", order_id="ORD-101")
    b.tool("check_shipping", order_value=499)
    sa = a.end([("customer", "Where is ORD-101?")])
    sb = b.end([("customer", "Shipping on 499?")])
    assert [x["tool"] for x in sa["summary"]["actions_taken"]] == ["get_order_details"]
    assert [x["tool"] for x in sb["summary"]["actions_taken"]] == ["check_shipping"]
    assert sa["transcript"] == [{"speaker": "customer", "text": "Where is ORD-101?"}]
    assert sb["summary"]["session_id"] == b.id != a.id


def test_cannot_end_another_sessions_call(start_call: Callable[[], Call], voice_client: TestClient) -> None:
    a, b = start_call(), start_call()
    r = voice_client.post(f"/api/voice/sessions/{a.id}/end", json={"transcript": []}, headers=b.headers)
    assert r.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"transcript": [{"speaker": "manager", "text": "hi"}]},
        {"transcript": [{"speaker": "customer", "text": ""}]},
        {"transcript": [{"speaker": "customer", "text": "x" * 4001}]},
        {"transcript": [{"speaker": "customer", "text": "hi", "time": 1}]},
        {"transcript": [], "end_reason": "bored"},
        {"transcript": [], "client_tool_failures": -1},
        {"transcript": [{"speaker": "customer", "text": "hi"}] * 401},
    ],
)
def test_end_request_validation(start_call: Callable[[], Call], voice_client: TestClient, body: dict[str, Any]) -> None:
    call = start_call()
    r = voice_client.post(f"/api/voice/sessions/{call.id}/end", json=body, headers=call.headers)
    assert r.status_code == 422


def test_summary_stored_with_session(start_call: Callable[[], Call], conn: sqlite3.Connection) -> None:
    call = start_call()
    out = call.end([("customer", "Hello")])
    stored = conn.execute("SELECT summary_json FROM voice_summaries WHERE session_id = ?", (call.id,)).fetchone()[0]
    assert json.loads(stored) == out["summary"]
    assert conn.execute("SELECT status FROM voice_sessions WHERE session_id = ?", (call.id,)).fetchone()[0] == "ended"

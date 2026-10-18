"""Post-call summary, built by rules from facts this server recorded.

No language model writes this summary, so it can't invent anything:
- actions_taken and every outcome come from voice_tool_calls, i.e. tools this
  server actually executed in this session;
- order_id is only ever an ID a tool looked up successfully;
- customer_issue is the customer's first transcribed utterance, quoted verbatim;
- when the record doesn't show how something ended, it says so instead of
  claiming a resolution.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Literal

Intent = Literal[
    "ORDER_TRACKING",
    "CANCELLATION",
    "RETURN_REFUND",
    "DAMAGED_OR_DEFECTIVE",
    "SHIPPING_QUESTION",
    "COD_QUESTION",
    "GENERAL_INQUIRY",
    "NO_CONVERSATION",
]
Resolution = Literal["RESOLVED", "POLICY_DECLINED", "NEEDS_FOLLOW_UP", "NOT_DETERMINED", "NO_CONVERSATION"]

# Most specific first: a call that looked up an order and then cancelled it is a cancellation.
_INTENT_PRIORITY: list[tuple[str, Intent]] = [
    ("cancel_order", "CANCELLATION"),
    ("check_cancellation_eligibility", "CANCELLATION"),
    ("damage_claim", "DAMAGED_OR_DEFECTIVE"),
    ("check_return_eligibility", "RETURN_REFUND"),
    ("check_shipping", "SHIPPING_QUESTION"),
    ("check_cod", "COD_QUESTION"),
    ("get_order_details", "ORDER_TRACKING"),
]

_ORDER_ERRORS = {"ORDER_NOT_FOUND", "ORDER_ID_INVALID", "ORDER_ID_MISSING"}
_SYSTEM_ERRORS = {"DATABASE_UNAVAILABLE", "TOOL_UNAVAILABLE", "INTERNAL_ERROR"}
_UNEXPECTED_ENDS = {
    "disconnected": "the connection dropped",
    "timeout": "it reached the time limit",
    "error": "an error",
}


def _action(row: sqlite3.Row) -> dict[str, Any]:
    response = json.loads(row["result_json"])
    result = response.get("result") or {}
    action: dict[str, Any] = {
        "tool": row["name"],
        "order_id": row["order_id"],
        "ok": bool(row["ok"]),
        "outcome": row["outcome"],
        "at": row["created_at"],
    }
    if row["ok"]:
        if "reason_code" in result:
            action["reason_code"] = result["reason_code"]
            action["check"] = result.get("check")
        if row["name"] == "cancel_order":
            action["cancelled"] = bool(result.get("cancelled"))
    else:
        action["error_code"] = response["error"]["code"]
    return action


def _describe(action: dict[str, Any], tool_results: dict[str, Any]) -> str:
    """One sentence per action, using only recorded results."""
    oid = action["order_id"] or "an order"
    if not action["ok"]:
        code = action["error_code"]
        if code in _ORDER_ERRORS:
            return f"Order lookup failed ({code}) for {oid}."
        return f"{action['tool']} failed ({code})."
    tool = action["tool"]
    result = tool_results
    if tool == "get_order_details":
        summary = (result.get("timing") or {}).get("summary")
        return f"Looked up {oid}: {result.get('status')}" + (f", {summary}." if summary else ".")
    if tool == "cancel_order":
        return f"{oid} cancelled." if action.get("cancelled") else f"{oid} not cancelled: {result.get('reason')}"
    return f"{result.get('check', tool)} check for {oid}: {result.get('outcome')} ({result.get('reason_code')})."


def build_summary(
    *,
    session: sqlite3.Row,
    tool_rows: list[sqlite3.Row],
    transcript: list[dict[str, str]],
    client_tool_failures: int,
    ended_at: datetime,
    end_reason: str = "customer_ended",
) -> dict[str, Any]:
    actions = [_action(r) for r in tool_rows]
    results = [(json.loads(r["result_json"]).get("result") or {}) for r in tool_rows]
    customer_turns = [t["text"] for t in transcript if t["speaker"] == "customer" and t["text"].strip()]

    # Which kinds of tools ran successfully, and what they decided.
    kinds = set()
    for a in actions:
        if a["ok"]:
            kinds.add("damage_claim" if a.get("check") == "damage_claim" else a["tool"])
    intent: Intent = "NO_CONVERSATION" if not customer_turns and not actions else "GENERAL_INQUIRY"
    for kind, mapped in _INTENT_PRIORITY:
        if kind in kinds:
            intent = mapped
            break

    looked_up = [a["order_id"] for a in actions if a["ok"] and a["order_id"]]
    order_ids = list(dict.fromkeys(looked_up))

    follow_up: list[str] = []
    unresolved: list[str] = []
    declined = False
    cancelled = any(a.get("cancelled") for a in actions)

    # A failed order lookup is unresolved only if no successful lookup came after it
    # (otherwise the customer most likely corrected the number).
    last_success = max((i for i, a in enumerate(actions) if a["ok"] and a["order_id"]), default=-1)
    failed_lookups = {
        a["order_id"] or "unknown"
        for i, a in enumerate(actions)
        if not a["ok"] and a["error_code"] in _ORDER_ERRORS and i > last_success
    }
    for oid in sorted(failed_lookups - set(order_ids)):
        unresolved.append(f"Couldn't find order {oid}; the customer may need to verify the order number.")

    system_failures = sum(1 for a in actions if not a["ok"] and a["error_code"] in _SYSTEM_ERRORS)
    if system_failures or client_tool_failures:
        n = system_failures + client_tool_failures
        follow_up.append(f"{n} tool call(s) failed because order records were unavailable.")

    # The call stopped before the customer ended it: they may not have heard Aria's last answer.
    if end_reason in _UNEXPECTED_ENDS and intent != "NO_CONVERSATION":
        follow_up.append(
            f"The call ended unexpectedly ({_UNEXPECTED_ENDS[end_reason]}); "
            "the customer may not have heard the final answer."
        )

    # The latest decision per (check, order) is the one that stands.
    latest: dict[tuple[str, str | None], dict[str, Any]] = {}
    for a, r in zip(actions, results, strict=True):
        if a["ok"] and "check" in a:
            latest[(str(a["check"]), a["order_id"])] = r
    for (check, oid), r in latest.items():
        outcome = r.get("outcome")
        if outcome == "POLICY_UNSPECIFIED":
            follow_up.append(f"{check} for {oid or 'the amount asked'}: the policy doesn't specify this case.")
        elif outcome == "NEEDS_INFO":
            unresolved.append(f"{check} for {oid}: still needed more information ({r.get('reason_code')}).")
        elif outcome == "NOT_ELIGIBLE" and check in ("cancellation", "return", "damage_claim"):
            declined = True
        # An ELIGIBLE cancellation that wasn't cancelled is not flagged: the customer may
        # only have asked whether they could, and the record can't tell those apart.

    for a in actions:
        if a["tool"] == "cancel_order" and a["ok"] and not a.get("cancelled"):
            declined = True

    if intent == "NO_CONVERSATION":
        resolution: Resolution = "NO_CONVERSATION"
    elif follow_up:
        resolution = "NEEDS_FOLLOW_UP"
    elif declined and not cancelled:
        resolution = "POLICY_DECLINED"
    elif unresolved:
        resolution = "NOT_DETERMINED"
    elif any(a["ok"] for a in actions):
        resolution = "RESOLVED"
    else:
        # Talked, but no tool ran: nothing on record shows how it ended.
        resolution = "NOT_DETERMINED"

    sentences = [_describe(a, r) for a, r in zip(actions, results, strict=True)]
    if not actions and customer_turns:
        sentences.append("No order or policy tool was used, so no outcome is on record.")
    if intent == "NO_CONVERSATION":
        sentences.append("The call ended before the customer said anything.")

    final_outcome = {
        "RESOLVED": "Aria answered using order records and policy checks.",
        "POLICY_DECLINED": "The request was outside policy and was declined.",
        "NEEDS_FOLLOW_UP": "Part of the request couldn't be completed and needs follow-up.",
        "NOT_DETERMINED": "The call record doesn't show a final outcome.",
        "NO_CONVERSATION": "No conversation took place.",
    }[resolution]
    if cancelled:
        final_outcome = "Order cancelled at the customer's request. " + final_outcome

    started = datetime.fromisoformat(session["created_at"])
    return {
        "session_id": session["session_id"],
        "started_at": session["created_at"],
        "ended_at": ended_at.isoformat(),
        "duration_seconds": max(0, int((ended_at - started).total_seconds())),
        "end_reason": end_reason,
        "customer_intent": intent,
        "customer_issue": customer_turns[0] if customer_turns else None,
        "order_id": order_ids[-1] if order_ids else None,
        "order_ids": order_ids,
        "actions_taken": actions,
        "resolution_status": resolution,
        "final_outcome": final_outcome,
        "follow_up_required": bool(follow_up or unresolved),
        "follow_up_reasons": follow_up,
        "unresolved_issues": unresolved,
        "call_summary": " ".join(sentences) if sentences else None,
        "transcript_turns": len(transcript),
        "summary_source": "rules: built from tools this server executed and the call transcript; no AI-written text",
    }

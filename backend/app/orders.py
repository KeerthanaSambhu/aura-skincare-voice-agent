"""Order lookup: get_order_details(order_id).

The database is the only source of order facts. If a record doesn't exist, this
module says so; it never constructs an order.
"""

import sqlite3
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .errors import order_not_found
from .order_ids import normalize_order_id

MOCK_DATA_NOTE = (
    "Mock assessment data. There is no live carrier tracking; status and timing come only from this record, "
    "and delivery estimates are fixed mock values."
)


def parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def fetch_order_row(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise order_not_found(order_id)
    return row


def _clock_time(moment: datetime) -> str:
    """6 PM, 6:30 PM"""
    hour = moment.strftime("%I").lstrip("0")
    minutes = "" if moment.minute == 0 else f":{moment.minute:02d}"
    return f"{hour}{minutes} {moment.strftime('%p')}"


def _ago(delta_days: int) -> str:
    if delta_days <= 0:
        return "today"
    if delta_days == 1:
        return "yesterday"
    return f"{delta_days} days ago"


def describe_timing(row: sqlite3.Row, now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    """Timing facts relative to `now`, plus one plain-language summary sentence."""
    local_now = now.astimezone(tz)
    ordered_at = parse_ts(row["ordered_at"])
    expected_by = parse_ts(row["expected_delivery_by"])
    delivered_at = parse_ts(row["delivered_at"])
    cancelled_at = parse_ts(row["cancelled_at"])

    timing: dict[str, Any] = {
        "ordered_at": row["ordered_at"],
        "expected_delivery_by": row["expected_delivery_by"],
        "expected_delivery_passed": None,
        "delivered_at": row["delivered_at"],
        "days_since_delivery": None,
        "hours_since_order": None,
        "cancelled_at": row["cancelled_at"],
        "summary": None,
    }
    parts: list[str] = []

    if delivered_at is not None:
        days = max(0, (local_now.date() - delivered_at.astimezone(tz).date()).days)
        timing["days_since_delivery"] = days
        parts.append(f"Delivered {_ago(days)}")

    if expected_by is not None and row["status"] not in ("Delivered", "Cancelled"):
        # Fixed mock snapshot, not a live estimate: the brief says ORD-101 is
        # "Expected by 6 PM today", so that is what every lookup says, whatever
        # the time. Only the stored time of day is used; it's restated for the
        # current date and never compared with the clock, so it can't read as
        # late. expected_delivery_passed stays None: it isn't evaluated.
        snapshot = datetime.combine(local_now.date(), expected_by.astimezone(tz).timetz())
        timing["expected_delivery_by"] = snapshot.isoformat()
        parts.append(f"Expected by {_clock_time(snapshot)} today")

    if ordered_at is not None:
        hours = max(0, int((now - ordered_at).total_seconds() // 3600))
        timing["hours_since_order"] = hours
        if row["status"] == "Processing":
            if hours < 1:
                parts.append("Ordered less than an hour ago")
            elif hours < 48:
                parts.append(f"Ordered {hours} hour{'s' if hours != 1 else ''} ago")
            else:
                parts.append(f"Ordered {hours // 24} days ago")

    if cancelled_at is not None:
        days = (local_now.date() - cancelled_at.astimezone(tz).date()).days
        parts.append(f"Cancelled {_ago(days)}")

    timing["summary"] = ". ".join(parts) if parts else None
    return timing


def order_to_dict(row: sqlite3.Row, now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    return {
        "order_id": row["order_id"],
        "customer_name": row["customer_name"],
        "product": row["product"],
        "value_inr": row["value_inr"],
        "value_display": f"₹{row['value_inr']:,}",
        "status": row["status"],
        "carrier": row["carrier"],
        "tracking_id": row["tracking_id"],
        "timing": describe_timing(row, now, tz),
        "data_note": MOCK_DATA_NOTE,
    }


def get_order_details(
    conn: sqlite3.Connection, raw_order_id: str | None, now: datetime, tz: ZoneInfo
) -> dict[str, Any]:
    """Look up one order. Raises AppError for missing, invalid or unknown IDs."""
    order_id = normalize_order_id(raw_order_id)
    return order_to_dict(fetch_order_row(conn, order_id), now, tz)

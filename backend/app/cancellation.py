"""cancel_order(order_id): the only operation that changes an order.

Safety rules:
1. BEGIN IMMEDIATE takes SQLite's write lock before reading, so two requests
   can't both see "Processing" and both cancel.
2. The status is re-read inside that transaction, immediately before the change.
3. The UPDATE is conditional (WHERE status = 'Processing'); if it changes
   anything other than exactly one row, the transaction is rolled back.
4. Success is reported only after COMMIT returns.

Mock system: this updates the demo SQLite record only. No real order,
payment or carrier is affected.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from .errors import order_not_found

CancelOutcome = Literal["CANCELLED", "NOT_ELIGIBLE", "ALREADY_CANCELLED"]

MOCK_NOTE = "Mock assessment system: only the demo database record changed. No real order or payment was affected."


@dataclass
class CancelResult:
    order_id: str
    cancelled: bool
    outcome: CancelOutcome
    previous_status: str
    status: str
    cancelled_at: str | None
    reason: str
    next_step: str
    note: str = MOCK_NOTE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cancel_order(conn: sqlite3.Connection, order_id: str, now: datetime) -> CancelResult:
    """Cancel a Processing order. `order_id` must already be normalised."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT status, cancelled_at FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise order_not_found(order_id)

        status = row["status"]
        if status == "Cancelled":
            conn.execute("ROLLBACK")
            return CancelResult(
                order_id,
                False,
                "ALREADY_CANCELLED",
                status,
                status,
                row["cancelled_at"],
                f"{order_id} was already cancelled.",
                "Tell the customer it's already cancelled. Nothing more is needed.",
            )
        if status != "Processing":
            conn.execute("ROLLBACK")
            next_step = (
                "The customer may refuse delivery at the doorstep."
                if status in ("Shipped", "Out for Delivery")
                else "If they want to send it back, check return eligibility instead."
            )
            return CancelResult(
                order_id,
                False,
                "NOT_ELIGIBLE",
                status,
                status,
                None,
                f"{order_id} is {status}. Only Processing orders can be cancelled.",
                next_step,
            )

        cancelled_at = now.isoformat()
        cursor = conn.execute(
            "UPDATE orders SET status = 'Cancelled', cancelled_at = ? WHERE order_id = ? AND status = 'Processing'",
            (cancelled_at, order_id),
        )
        if cursor.rowcount != 1:
            conn.execute("ROLLBACK")
            raise sqlite3.OperationalError(f"expected to update 1 row, updated {cursor.rowcount}")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    return CancelResult(
        order_id,
        True,
        "CANCELLED",
        "Processing",
        "Cancelled",
        cancelled_at,
        f"{order_id} has been cancelled.",
        "Confirm to the customer that the order is cancelled.",
    )

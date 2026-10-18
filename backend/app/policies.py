"""Deterministic policy checks.

Every business rule lives here as plain Python, so eligibility is decided by
code and tests, not by the language model. Each check returns a PolicyResult
with an outcome, a machine-readable reason code, a plain-language reason, the
next step for the agent, and the verbatim policy it applied.

Boundary choices (the brief doesn't say, so these are stated explicitly):
- "Within 7 days of delivery" includes exactly 7 days (168 hours) after delivery.
- "Within 48 hours of delivery" includes exactly 48 hours after delivery.
- "Up to ₹2,500" for COD includes ₹2,500.
- Shipping for exactly ₹499 is not covered by the policy -> POLICY_UNSPECIFIED.
"""

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from .orders import parse_ts

# ── Verbatim policy text from the assessment brief (section 3) ───────────────
SHIPPING_POLICY = (
    "Free delivery on orders above ₹499. Orders below ₹499 have a ₹50 shipping fee. "
    "Standard delivery takes 3–5 business days."
)
RETURN_POLICY = (
    "Returns are accepted within 7 days of delivery for unopened, unused products in original packaging. "
    "Damaged or defective products must be reported within 48 hours of delivery with photos for replacement."
)
CANCELLATION_POLICY = (
    "Orders can be cancelled only while their status is Processing. Once an order is Shipped or Out for "
    "Delivery, it cannot be cancelled (customers may refuse delivery at doorstep)."
)
COD_POLICY = "COD is available for orders up to ₹2,500. Customers can pay by cash or UPI at the doorstep."

FREE_SHIPPING_ABOVE_INR = Decimal(499)
SHIPPING_FEE_INR = 50
STANDARD_DELIVERY = "3–5 business days"
RETURN_WINDOW = timedelta(days=7)
DAMAGE_REPORT_WINDOW = timedelta(hours=48)
COD_LIMIT_INR = Decimal(2500)
COD_PAYMENT_METHODS = ["cash", "UPI"]

Outcome = Literal["ELIGIBLE", "NOT_ELIGIBLE", "NEEDS_INFO", "POLICY_UNSPECIFIED"]
Check = Literal["cancellation", "return", "damage_claim", "shipping", "cod"]
ReturnReason = Literal["unwanted", "damaged", "defective"]


@dataclass
class PolicyResult:
    check: Check
    order_id: str | None
    outcome: Outcome
    reason_code: str
    reason: str
    next_step: str
    policy: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def eligible(self) -> bool | None:
        """True / False when the policy decides; None when more info is needed or the policy is silent."""
        return {"ELIGIBLE": True, "NOT_ELIGIBLE": False}.get(self.outcome)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["eligible"] = self.eligible
        return data


# ── Cancellation ─────────────────────────────────────────────────────────────
def check_cancellation(order: sqlite3.Row) -> PolicyResult:
    oid, status = order["order_id"], order["status"]

    def result(outcome: Outcome, code: str, reason: str, next_step: str) -> PolicyResult:
        return PolicyResult(
            "cancellation", oid, outcome, code, reason, next_step, CANCELLATION_POLICY, {"status": status}
        )

    if status == "Processing":
        return result(
            "ELIGIBLE",
            "STATUS_PROCESSING",
            f"{oid} is still Processing, so it can be cancelled.",
            "Confirm the customer wants to cancel, then call cancel_order. "
            "Don't say it's cancelled until cancel_order succeeds.",
        )
    if status in ("Shipped", "Out for Delivery"):
        code = "STATUS_SHIPPED" if status == "Shipped" else "STATUS_OUT_FOR_DELIVERY"
        return result(
            "NOT_ELIGIBLE",
            code,
            f"{oid} is {status}. Orders can only be cancelled while Processing.",
            "Explain it can't be cancelled now. The customer may refuse delivery at the doorstep.",
        )
    if status == "Delivered":
        return result(
            "NOT_ELIGIBLE",
            "STATUS_DELIVERED",
            f"{oid} has already been delivered, so cancellation no longer applies.",
            "If the customer wants to send it back, check return eligibility instead.",
        )
    if status == "Cancelled":
        return result(
            "NOT_ELIGIBLE",
            "ALREADY_CANCELLED",
            f"{oid} is already cancelled.",
            "Tell the customer the order is already cancelled. Nothing more is needed.",
        )
    return result(
        "NOT_ELIGIBLE",
        "STATUS_UNKNOWN",
        f"{oid} has an unrecognised status, so cancellation can't be confirmed.",
        "Don't promise a cancellation. Say you can't confirm it right now.",
    )


# ── Returns and damaged / defective claims ───────────────────────────────────
def _delivered_at(order: sqlite3.Row) -> datetime | None:
    return parse_ts(order["delivered_at"]) if order["status"] == "Delivered" else None


def _not_delivered(order: sqlite3.Row, check: Check, policy: str) -> PolicyResult:
    oid, status = order["order_id"], order["status"]
    if status == "Processing":
        next_step = "It hasn't shipped yet. If the customer no longer wants it, check cancellation eligibility."
    elif status in ("Shipped", "Out for Delivery"):
        next_step = "It hasn't been delivered yet. The customer may refuse delivery at the doorstep."
    elif status == "Cancelled":
        next_step = "The order is cancelled, so there is nothing to return."
    else:
        next_step = "Don't promise a return. Say you can't confirm the delivery date."
    return PolicyResult(
        check,
        oid,
        "NOT_ELIGIBLE",
        "NOT_DELIVERED",
        f"{oid} is {status}, and returns and damage claims only apply to delivered orders.",
        next_step,
        policy,
        {"status": status},
    )


def check_damage_claim(order: sqlite3.Row, has_photos: bool | None, now: datetime) -> PolicyResult:
    """Damaged or defective items: report within 48 hours of delivery, with photos, for replacement."""
    oid = order["order_id"]
    delivered_at = _delivered_at(order)
    if delivered_at is None:
        return _not_delivered(order, "damage_claim", RETURN_POLICY)

    elapsed = now - delivered_at
    deadline = delivered_at + DAMAGE_REPORT_WINDOW
    details = {
        "status": order["status"],
        "delivered_at": order["delivered_at"],
        "hours_since_delivery": max(0, int(elapsed.total_seconds() // 3600)),
        "report_deadline": deadline.isoformat(),
        "remedy": "replacement",
    }

    def result(outcome: Outcome, code: str, reason: str, next_step: str) -> PolicyResult:
        return PolicyResult("damage_claim", oid, outcome, code, reason, next_step, RETURN_POLICY, details)

    if elapsed > DAMAGE_REPORT_WINDOW:
        return result(
            "NOT_ELIGIBLE",
            "OUTSIDE_DAMAGE_WINDOW",
            f"Damaged or defective items must be reported within 48 hours of delivery. "
            f"{oid} was delivered {details['hours_since_delivery']} hours ago.",
            "Explain the 48-hour reporting window has passed. Don't promise a replacement or refund.",
        )
    if has_photos is None:
        return result(
            "NEEDS_INFO",
            "PHOTOS_UNCONFIRMED",
            "A damaged or defective claim needs photos, and it isn't known yet whether the customer has them.",
            "Ask the customer whether they can share photos of the damage or defect.",
        )
    if has_photos is False:
        return result(
            "NOT_ELIGIBLE",
            "PHOTOS_REQUIRED",
            "The policy requires photos to report a damaged or defective item.",
            "Ask the customer to take photos and report it before the 48-hour deadline.",
        )
    return result(
        "ELIGIBLE",
        "WITHIN_48_HOURS_WITH_PHOTOS",
        f"{oid} was reported within 48 hours of delivery, with photos.",
        "Tell the customer it qualifies for a replacement under policy. The policy specifies a "
        "replacement, not a refund. This mock system can't collect photos or create the replacement.",
    )


def check_return(
    order: sqlite3.Row,
    opened: bool | None,
    reason: ReturnReason | None,
    now: datetime,
    has_photos: bool | None = None,
) -> PolicyResult:
    """Standard returns, or damaged/defective claims when the reason says so."""
    if reason in ("damaged", "defective"):
        return check_damage_claim(order, has_photos, now)

    oid = order["order_id"]
    delivered_at = _delivered_at(order)
    if delivered_at is None:
        return _not_delivered(order, "return", RETURN_POLICY)

    elapsed = now - delivered_at
    details = {
        "status": order["status"],
        "delivered_at": order["delivered_at"],
        "days_since_delivery": max(0, elapsed.days),
        "return_deadline": (delivered_at + RETURN_WINDOW).isoformat(),
    }

    def result(outcome: Outcome, code: str, why: str, next_step: str) -> PolicyResult:
        return PolicyResult("return", oid, outcome, code, why, next_step, RETURN_POLICY, details)

    if reason is None:
        return result(
            "NEEDS_INFO",
            "REASON_MISSING",
            "It isn't known why the customer wants to return the item.",
            "Ask whether they no longer want it, or whether it arrived damaged or defective.",
        )
    if elapsed > RETURN_WINDOW:
        return result(
            "NOT_ELIGIBLE",
            "OUTSIDE_RETURN_WINDOW",
            f"Returns are accepted within 7 days of delivery. {oid} was delivered "
            f"{details['days_since_delivery']} days ago.",
            "Politely explain it's outside the 7-day return window. Don't promise a return or refund.",
        )
    if opened is None:
        return result(
            "NEEDS_INFO",
            "OPENED_UNKNOWN",
            "Returns need the product unopened, unused and in its original packaging, "
            "and it isn't known yet whether it has been opened.",
            "Ask whether the product is unopened, unused and still in its original packaging.",
        )
    if opened:
        return result(
            "NOT_ELIGIBLE",
            "OPENED_OR_USED",
            "Only unopened, unused products in original packaging can be returned.",
            "Politely explain an opened or used product can't be returned. Don't promise a refund. "
            "If it arrived damaged or defective, check that instead.",
        )
    return result(
        "ELIGIBLE",
        "WITHIN_WINDOW_UNOPENED",
        f"{oid} is within 7 days of delivery and the customer says it is unopened.",
        "Tell the customer the return is accepted under policy, provided the product is unused and in "
        "its original packaging. This mock system can't create the return, so don't quote refund dates.",
    )


# ── Shipping and cash on delivery ────────────────────────────────────────────
def _inr(value: Decimal) -> str:
    """₹699, ₹2,500, ₹499.50"""
    text = f"{value:,.2f}"
    return "₹" + (text[:-3] if text.endswith(".00") else text)


def check_shipping(order_value: Decimal, order_id: str | None = None) -> PolicyResult:
    details: dict[str, Any] = {"order_value_inr": str(order_value), "standard_delivery": STANDARD_DELIVERY}

    if order_value > FREE_SHIPPING_ABOVE_INR:
        details["shipping_fee_inr"] = 0
        return PolicyResult(
            "shipping",
            order_id,
            "ELIGIBLE",
            "ABOVE_499",
            f"{_inr(order_value)} is above ₹499, so delivery is free.",
            f"Tell the customer delivery is free and standard delivery takes {STANDARD_DELIVERY}.",
            SHIPPING_POLICY,
            details,
        )
    if order_value < FREE_SHIPPING_ABOVE_INR:
        details["shipping_fee_inr"] = SHIPPING_FEE_INR
        return PolicyResult(
            "shipping",
            order_id,
            "NOT_ELIGIBLE",
            "BELOW_499",
            f"{_inr(order_value)} is below ₹499, so a ₹50 shipping fee applies.",
            f"Tell the customer there's a ₹50 shipping fee and standard delivery takes {STANDARD_DELIVERY}.",
            SHIPPING_POLICY,
            details,
        )
    details["shipping_fee_inr"] = None
    return PolicyResult(
        "shipping",
        order_id,
        "POLICY_UNSPECIFIED",
        "EXACTLY_499",
        "The shipping policy covers orders above and below ₹499, but not exactly ₹499.",
        "Say the policy doesn't state the fee for exactly ₹499, so you can't confirm it. Don't guess or "
        f"promise a fee or free delivery. Standard delivery still takes {STANDARD_DELIVERY}.",
        SHIPPING_POLICY,
        details,
    )


def check_cod(order_value: Decimal, order_id: str | None = None) -> PolicyResult:
    details: dict[str, Any] = {
        "order_value_inr": str(order_value),
        "cod_limit_inr": int(COD_LIMIT_INR),
        "payment_methods": COD_PAYMENT_METHODS,
    }
    if order_value <= COD_LIMIT_INR:
        return PolicyResult(
            "cod",
            order_id,
            "ELIGIBLE",
            "WITHIN_COD_LIMIT",
            f"{_inr(order_value)} is within the ₹2,500 cash-on-delivery limit.",
            "Tell the customer cash on delivery is available; they can pay by cash or UPI at the doorstep.",
            COD_POLICY,
            details,
        )
    return PolicyResult(
        "cod",
        order_id,
        "NOT_ELIGIBLE",
        "ABOVE_COD_LIMIT",
        f"{_inr(order_value)} is above the ₹2,500 cash-on-delivery limit.",
        "Explain cash on delivery is only available for orders up to ₹2,500.",
        COD_POLICY,
        details,
    )

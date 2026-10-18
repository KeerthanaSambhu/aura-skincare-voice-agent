"""Pydantic models for request validation and the documented response shapes."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .policies import Check, Outcome, ReturnReason


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Requests ─────────────────────────────────────────────────────────────────
class ReturnEligibilityRequest(StrictBody):
    opened: bool | None = Field(
        default=None, description="True if the product has been opened or used. Omit if the customer hasn't said."
    )
    reason: ReturnReason | None = Field(
        default=None, description="'unwanted' for a standard return; 'damaged' or 'defective' for a replacement claim."
    )
    has_photos: bool | None = Field(
        default=None, description="Damaged/defective claims only: can the customer share photos?"
    )


# ── Responses ────────────────────────────────────────────────────────────────
class Timing(BaseModel):
    ordered_at: str | None
    expected_delivery_by: str | None
    expected_delivery_passed: bool | None
    delivered_at: str | None
    days_since_delivery: int | None
    hours_since_order: int | None
    cancelled_at: str | None
    summary: str | None = Field(
        description="Plain-language timing, phrased relative to now, e.g. 'Delivered 14 days ago'."
    )


class OrderDetails(BaseModel):
    order_id: str
    customer_name: str
    product: str
    value_inr: int
    value_display: str
    status: Literal["Processing", "Shipped", "Out for Delivery", "Delivered", "Cancelled"]
    carrier: str | None
    tracking_id: str | None
    timing: Timing
    data_note: str


class PolicyResultModel(BaseModel):
    check: Check
    order_id: str | None
    outcome: Outcome
    eligible: bool | None = Field(
        description="True/False when the policy decides; null when more info is needed or the policy is silent."
    )
    reason_code: str
    reason: str
    next_step: str
    policy: str = Field(description="The policy text applied, verbatim from the brief.")
    details: dict[str, Any]


class CancelResultModel(BaseModel):
    order_id: str
    cancelled: bool
    outcome: Literal["CANCELLED", "NOT_ELIGIBLE", "ALREADY_CANCELLED"]
    previous_status: str
    status: str
    cancelled_at: str | None
    reason: str
    next_step: str
    note: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    order_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]

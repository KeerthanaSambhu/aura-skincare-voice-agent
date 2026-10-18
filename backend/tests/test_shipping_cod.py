"""15-17. Shipping fee, the unspecified ₹499 case, and the COD limit."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.policies import check_cod, check_shipping


def shipping(client: TestClient, **params: object) -> dict[str, object]:
    response = client.get("/api/policies/shipping", params=params)
    assert response.status_code == 200, response.text
    result: dict[str, object] = response.json()
    return result


# ── 15. Below and above ₹499 ────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["1", "250", "498", "498.99"])
def test_below_499_has_50_fee(client: TestClient, value: str) -> None:
    body = shipping(client, order_value=value)
    assert (body["outcome"], body["reason_code"]) == ("NOT_ELIGIBLE", "BELOW_499")
    assert body["details"]["shipping_fee_inr"] == 50  # type: ignore[index]
    assert body["details"]["standard_delivery"] == "3–5 business days"  # type: ignore[index]


@pytest.mark.parametrize("value", ["499.01", "500", "699", "2500"])
def test_above_499_is_free(client: TestClient, value: str) -> None:
    body = shipping(client, order_value=value)
    assert (body["outcome"], body["eligible"], body["reason_code"]) == ("ELIGIBLE", True, "ABOVE_499")
    assert body["details"]["shipping_fee_inr"] == 0  # type: ignore[index]


def test_shipping_by_order_id_uses_stored_value(client: TestClient) -> None:
    body = shipping(client, order_id="ord 101")
    assert (body["order_id"], body["outcome"]) == ("ORD-101", "ELIGIBLE")


# ── 16. Exactly ₹499 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["499", "499.00"])
def test_exactly_499_is_policy_unspecified(client: TestClient, value: str) -> None:
    body = shipping(client, order_value=value)
    assert (body["outcome"], body["eligible"], body["reason_code"]) == ("POLICY_UNSPECIFIED", None, "EXACTLY_499")
    assert body["details"]["shipping_fee_inr"] is None  # type: ignore[index]
    assert "Don't guess" in str(body["next_step"])


def test_ord_102_is_exactly_499(client: TestClient) -> None:
    assert shipping(client, order_id="ORD-102")["outcome"] == "POLICY_UNSPECIFIED"


def test_policy_text_is_verbatim() -> None:
    assert check_shipping(Decimal(1)).policy == (
        "Free delivery on orders above ₹499. Orders below ₹499 have a ₹50 shipping fee. "
        "Standard delivery takes 3–5 business days."
    )


# ── 17. COD ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,eligible", [("1", True), ("2499.99", True), ("2500", True), ("2500.01", False), ("3000", False)]
)
def test_cod_limit(client: TestClient, value: str, eligible: bool) -> None:
    response = client.get("/api/policies/cod", params={"order_value": value})
    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is eligible
    assert body["reason_code"] == ("WITHIN_COD_LIMIT" if eligible else "ABOVE_COD_LIMIT")
    assert body["details"]["payment_methods"] == ["cash", "UPI"]


def test_cod_messages_format_rupees() -> None:
    assert check_cod(Decimal("2500")).reason.startswith("₹2,500 is within")
    assert check_cod(Decimal("2500.5")).reason.startswith("₹2,500.50 is above")


def test_cod_by_order_id(client: TestClient) -> None:
    body = client.get("/api/policies/cod", params={"order_id": "ORD-103"}).json()
    assert (body["order_id"], body["eligible"]) == ("ORD-103", True)

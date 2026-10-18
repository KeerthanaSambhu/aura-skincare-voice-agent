"""Errors that map to a structured JSON body and an HTTP status.

Every error response has the same shape:
    {"error": {"code": "ORDER_NOT_FOUND", "message": "...", "order_id": "ORD-999"}}
"""

from dataclasses import dataclass


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int
    order_id: str | None = None

    def body(self) -> dict[str, dict[str, str | None]]:
        error: dict[str, str | None] = {"code": self.code, "message": self.message}
        if self.order_id is not None:
            error["order_id"] = self.order_id
        return {"error": error}


def order_id_missing() -> AppError:
    return AppError("ORDER_ID_MISSING", "No order ID was given. Ask the customer for their order number.", 422)


def order_id_invalid(raw: str) -> AppError:
    shown = raw if len(raw) <= 40 else raw[:40] + "…"
    return AppError(
        "ORDER_ID_INVALID",
        f"'{shown}' isn't a valid order ID. Order IDs look like ORD-101. Ask the customer to repeat or check it.",
        422,
    )


def order_not_found(order_id: str) -> AppError:
    return AppError(
        "ORDER_NOT_FOUND",
        f"No order with ID {order_id} exists. Ask the customer to repeat or verify the order number.",
        404,
        order_id,
    )


def database_unavailable() -> AppError:
    return AppError("DATABASE_UNAVAILABLE", "Order records are temporarily unavailable. Please try again shortly.", 503)

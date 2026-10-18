"""FastAPI app: health, order lookup, policy checks and cancellation.

Run locally:  uvicorn app.main:app --reload   (from the backend/ directory)
Interactive docs: http://localhost:8000/docs
"""

import logging
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, closing
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .cancellation import cancel_order
from .clock import Clock, utc_now
from .config import Settings
from .errors import AppError, order_id_missing
from .logging_config import configure_logging
from .order_ids import normalize_order_id
from .orders import fetch_order_row, get_order_details
from .policies import PolicyResult, check_cancellation, check_cod, check_return, check_shipping
from .schemas import (
    CancelResultModel,
    ErrorResponse,
    HealthResponse,
    OrderDetails,
    PolicyResultModel,
    ReturnEligibilityRequest,
)
from .voice.routes import build_voice_router, default_minter_factory
from .voice.tokens import TokenMinter

logger = logging.getLogger("aura.api")

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Order not found"},
    422: {"model": ErrorResponse, "description": "Missing or invalid input"},
    503: {"model": ErrorResponse, "description": "Database unavailable"},
}


def create_app(
    settings: Settings | None = None,
    clock: Clock = utc_now,
    token_minter_factory: Callable[[], TokenMinter] | None = None,
) -> FastAPI:
    """Build the app. Tests pass a frozen clock and a fake token minter; production uses the defaults."""
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        seeded = db.prepare_database(settings.database_file, clock(), settings.tz)
        logger.info("database_ready", extra={"path": str(settings.database_file), "seeded_now": seeded})
        yield

    app = FastAPI(
        title="Aura AI backend",
        version="0.4.0",
        description="Mock order records, deterministic policy checks and order tools for Aria, "
        "Aura Skincare's voice support agent. Assessment demo only: not connected to any real "
        "order, carrier or payment system.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.clock = clock

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Session-Secret"],
    )

    # ── Logging and error handling ────────────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info("request_rejected", extra={"code": exc.code, "order_id": exc.order_id, "path": request.url.path})
        return JSONResponse(exc.body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path")) or "body" for err in exc.errors()
        ]
        message = "Invalid request: check " + ", ".join(sorted(set(fields))) + "."
        return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": message}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse({"error": {"code": code, "message": str(exc.detail)}}, status_code=exc.status_code)

    @app.exception_handler(sqlite3.Error)
    async def handle_db_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        logger.error("database_error", exc_info=exc, extra={"path": request.url.path})
        err = AppError(
            "DATABASE_UNAVAILABLE", "Order records are temporarily unavailable. Please try again shortly.", 503
        )
        return JSONResponse(err.body(), status_code=503)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", exc_info=exc, extra={"path": request.url.path})
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong on our side."}}, status_code=500
        )

    # ── Dependencies ──────────────────────────────────────────────────────
    def get_conn() -> Iterator[sqlite3.Connection]:
        with closing(db.connect(settings.database_file)) as conn:
            yield conn

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def log_policy(result: PolicyResult) -> dict[str, Any]:
        logger.info(
            "policy_check",
            extra={
                "check": result.check,
                "order_id": result.order_id,
                "outcome": result.outcome,
                "reason_code": result.reason_code,
            },
        )
        return result.to_dict()

    def order_value_or_id(
        conn: sqlite3.Connection, order_value: Decimal | None, order_id: str | None
    ) -> tuple[Decimal, str | None]:
        if (order_value is None) == (order_id is None):
            raise AppError("VALIDATION_ERROR", "Give exactly one of order_value or order_id.", 422)
        if order_id is not None:
            normalized = normalize_order_id(order_id)
            return Decimal(fetch_order_row(conn, normalized)["value_inr"]), normalized
        assert order_value is not None
        return order_value, None

    OrderValue = Annotated[
        Decimal | None,
        Query(gt=0, le=10_000_000, max_digits=10, decimal_places=2, description="Order value in rupees, e.g. 699"),
    ]
    OrderIdQuery = Annotated[str | None, Query(max_length=64, description="Use this order's stored value instead")]

    # ── Routes ────────────────────────────────────────────────────────────
    @app.get("/health", response_model=HealthResponse, tags=["health"], responses={503: {"model": HealthResponse}})
    def health() -> Any:
        try:
            with closing(db.connect(settings.database_file)) as conn:
                conn.execute("SELECT 1 FROM orders LIMIT 1").fetchall()
        except sqlite3.Error:
            logger.error("health_database_unavailable")
            return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
        return {"status": "ok", "database": "ok"}

    @app.get("/api/orders", include_in_schema=False)
    def order_id_not_given() -> None:
        raise order_id_missing()

    @app.get(
        "/api/orders/{order_id}",
        response_model=OrderDetails,
        tags=["orders"],
        responses=ERROR_RESPONSES,
        summary="get_order_details: look up one order",
    )
    def get_order(order_id: str, conn: Conn) -> Any:
        details = get_order_details(conn, order_id, app.state.clock(), settings.tz)
        logger.info("order_lookup", extra={"order_id": details["order_id"], "status": details["status"]})
        return details

    @app.get(
        "/api/orders/{order_id}/cancellation-eligibility",
        response_model=PolicyResultModel,
        tags=["policies"],
        responses=ERROR_RESPONSES,
        summary="check_cancellation_eligibility",
    )
    def cancellation_eligibility(order_id: str, conn: Conn) -> Any:
        return log_policy(check_cancellation(fetch_order_row(conn, normalize_order_id(order_id))))

    @app.post(
        "/api/orders/{order_id}/return-eligibility",
        response_model=PolicyResultModel,
        tags=["policies"],
        responses=ERROR_RESPONSES,
        summary="check_return_eligibility (standard, damaged or defective)",
    )
    def return_eligibility(order_id: str, body: ReturnEligibilityRequest, conn: Conn) -> Any:
        order = fetch_order_row(conn, normalize_order_id(order_id))
        return log_policy(check_return(order, body.opened, body.reason, app.state.clock(), body.has_photos))

    @app.post(
        "/api/orders/{order_id}/cancel",
        response_model=CancelResultModel,
        tags=["actions"],
        responses={**ERROR_RESPONSES, 409: {"model": CancelResultModel, "description": "Not cancellable"}},
        summary="cancel_order: cancel a Processing order",
    )
    def cancel(order_id: str, conn: Conn) -> Any:
        result = cancel_order(conn, normalize_order_id(order_id), app.state.clock())
        logger.info("cancel_order", extra={"order_id": result.order_id, "outcome": result.outcome})
        return JSONResponse(result.to_dict(), status_code=200 if result.cancelled else 409)

    @app.get(
        "/api/policies/shipping",
        response_model=PolicyResultModel,
        tags=["policies"],
        responses=ERROR_RESPONSES,
        summary="Shipping fee and delivery time for an order value",
    )
    def shipping(conn: Conn, order_value: OrderValue = None, order_id: OrderIdQuery = None) -> Any:
        value, oid = order_value_or_id(conn, order_value, order_id)
        return log_policy(check_shipping(value, oid))

    @app.get(
        "/api/policies/cod",
        response_model=PolicyResultModel,
        tags=["policies"],
        responses=ERROR_RESPONSES,
        summary="Cash-on-delivery availability for an order value",
    )
    def cod(conn: Conn, order_value: OrderValue = None, order_id: OrderIdQuery = None) -> Any:
        value, oid = order_value_or_id(conn, order_value, order_id)
        return log_policy(check_cod(value, oid))

    app.include_router(
        build_voice_router(
            settings,
            clock_getter=lambda: app.state.clock,
            conn_dependency=get_conn,
            minter_factory=token_minter_factory or default_minter_factory(settings),
        )
    )

    return app


app = create_app()

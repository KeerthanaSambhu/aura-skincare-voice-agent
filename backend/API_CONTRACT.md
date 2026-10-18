# Aura AI backend — API contract

The interface the frontend builds against. Base URL locally: `http://localhost:8000`. Every example below is real output from the API, captured with the clock frozen at 10:00 IST on 17 Oct 2026, right after seeding.

The server also publishes an OpenAPI schema at `/openapi.json` and interactive docs at `/docs`.

## Conventions

- **JSON in, JSON out.** Request bodies need `Content-Type: application/json`.
- **Order IDs** go in the URL path, URL-encoded (`encodeURIComponent`). The server normalises them: `ORD-101`, `ord 101`, `ORD101`, `Order 101`, `order no. 101`, `#101` and `101` all mean `ORD-101`. Digits split by a separator (`ORD-101-2`) are rejected rather than merged.
- **Money** is in rupees. Order values come back as whole-rupee integers (`value_inr`) plus a display string (`value_display`, e.g. `₹699`).
- **Timestamps** are ISO-8601 with an offset. `timing.summary` is a ready-to-say sentence, phrased relative to now.
- **"Not eligible" is an answer, not an error.** Eligibility checks return `200` with `outcome: NOT_ELIGIBLE`. Errors are reserved for bad input, unknown orders and server problems.
- **CORS** allows the origins in `ALLOWED_ORIGINS` (default `http://localhost:5173,http://localhost:4173`), methods `GET` and `POST`, headers `Content-Type` and `X-Session-Secret`.

## Endpoints

| Tool for Phase 4 | Method and path | Body / query | Success |
|---|---|---|---|
| — | `GET /health` | — | `200` |
| `get_order_details(order_id)` | `GET /api/orders/{order_id}` | — | `200` OrderDetails |
| `check_cancellation_eligibility(order_id)` | `GET /api/orders/{order_id}/cancellation-eligibility` | — | `200` PolicyResult |
| `check_return_eligibility(order_id, opened, reason, has_photos)` | `POST /api/orders/{order_id}/return-eligibility` | `{"opened"?, "reason"?, "has_photos"?}` | `200` PolicyResult |
| `cancel_order(order_id)` | `POST /api/orders/{order_id}/cancel` | — (no body) | `200` CancelResult, or `409` CancelResult if refused |
| `check_shipping(order_value | order_id)` | `GET /api/policies/shipping` | `?order_value=699` **or** `?order_id=ORD-101` | `200` PolicyResult |
| `check_cod(order_value | order_id)` | `GET /api/policies/cod` | `?order_value=3000` **or** `?order_id=ORD-101` | `200` PolicyResult |

Return-eligibility body fields, all optional:

| Field | Type | Meaning |
|---|---|---|
| `reason` | `"unwanted"` \| `"damaged"` \| `"defective"` | `unwanted` is a standard return. `damaged`/`defective` run the 48-hour replacement check. Missing → `NEEDS_INFO`. |
| `opened` | boolean | `true` if opened **or used**. Missing on a standard return → `NEEDS_INFO`. |
| `has_photos` | boolean | Damaged/defective only. Missing → `NEEDS_INFO`. |

Unknown fields are rejected (`422`), so a model can't sneak in e.g. `"refund": true`.

## Response shapes

### OrderDetails

```json
{
  "order_id": "ORD-101",
  "customer_name": "Priya Sharma",
  "product": "Vitamin C Serum (30ml)",
  "value_inr": 699,
  "value_display": "₹699",
  "status": "Out for Delivery",
  "carrier": "BlueDart",
  "tracking_id": "BD-982103",
  "timing": {
    "ordered_at": null,
    "expected_delivery_by": "2026-10-17T18:00:00+05:30",
    "expected_delivery_passed": null,
    "delivered_at": null,
    "days_since_delivery": null,
    "hours_since_order": null,
    "cancelled_at": null,
    "summary": "Expected by 6 PM today"
  },
  "data_note": "Mock assessment data. There is no live carrier tracking; status and timing come only from this record, and delivery estimates are fixed mock values."
}
```

`ordered_at` is `null` because the brief doesn't give an order date for ORD-101 or ORD-102. ORD-101's delivery estimate is a **fixed mock snapshot** of the brief's "Expected by 6 PM today": `summary` always says exactly that, whatever the time of day, `expected_delivery_by` is 6 PM IST on the current date, and `expected_delivery_passed` is `null` because it is never compared with the clock. It is not a carrier update; `data_note` says so.

### PolicyResult

Shared by every policy check.

| Field | Values |
|---|---|
| `check` | `cancellation`, `return`, `damage_claim`, `shipping`, `cod` |
| `outcome` | `ELIGIBLE`, `NOT_ELIGIBLE`, `NEEDS_INFO`, `POLICY_UNSPECIFIED` |
| `eligible` | `true` / `false`; `null` for `NEEDS_INFO` and `POLICY_UNSPECIFIED` |
| `reason_code` | Stable machine code (table below) |
| `reason` | Why, in one sentence |
| `next_step` | What Aria should say or do next |
| `policy` | The policy text applied, verbatim from the brief |
| `details` | Check-specific facts (deadlines, fees, status) |

For shipping, `ELIGIBLE` means free delivery and `NOT_ELIGIBLE` means the ₹50 fee applies.

Cancellation, ORD-101:

```json
{
  "check": "cancellation",
  "order_id": "ORD-101",
  "outcome": "NOT_ELIGIBLE",
  "eligible": false,
  "reason_code": "STATUS_OUT_FOR_DELIVERY",
  "reason": "ORD-101 is Out for Delivery. Orders can only be cancelled while Processing.",
  "next_step": "Explain it can't be cancelled now. The customer may refuse delivery at the doorstep.",
  "policy": "Orders can be cancelled only while their status is Processing. Once an order is Shipped or Out for Delivery, it cannot be cancelled (customers may refuse delivery at doorstep).",
  "details": {
    "status": "Out for Delivery"
  }
}
```

Return, ORD-102 opened (the brief's policy-enforcement example):

```json
{
  "check": "return",
  "order_id": "ORD-102",
  "outcome": "NOT_ELIGIBLE",
  "eligible": false,
  "reason_code": "OUTSIDE_RETURN_WINDOW",
  "reason": "Returns are accepted within 7 days of delivery. ORD-102 was delivered 14 days ago.",
  "next_step": "Politely explain it's outside the 7-day return window. Don't promise a return or refund.",
  "policy": "Returns are accepted within 7 days of delivery for unopened, unused products in original packaging. Damaged or defective products must be reported within 48 hours of delivery with photos for replacement.",
  "details": {
    "status": "Delivered",
    "delivered_at": "2026-10-03T04:30:00+00:00",
    "days_since_delivery": 14,
    "return_deadline": "2026-10-10T04:30:00+00:00"
  }
}
```

Shipping, ORD-102 (exactly ₹499, which the policy doesn't cover):

```json
{
  "check": "shipping",
  "order_id": "ORD-102",
  "outcome": "POLICY_UNSPECIFIED",
  "eligible": null,
  "reason_code": "EXACTLY_499",
  "reason": "The shipping policy covers orders above and below ₹499, but not exactly ₹499.",
  "next_step": "Say the policy doesn't state the fee for exactly ₹499, so you can't confirm it. Don't guess or promise a fee or free delivery. Standard delivery still takes 3–5 business days.",
  "policy": "Free delivery on orders above ₹499. Orders below ₹499 have a ₹50 shipping fee. Standard delivery takes 3–5 business days.",
  "details": {
    "order_value_inr": "499",
    "standard_delivery": "3–5 business days",
    "shipping_fee_inr": null
  }
}
```

### CancelResult

Success, `200`:

```json
{
  "order_id": "ORD-103",
  "cancelled": true,
  "outcome": "CANCELLED",
  "previous_status": "Processing",
  "status": "Cancelled",
  "cancelled_at": "2026-10-17T04:30:00+00:00",
  "reason": "ORD-103 has been cancelled.",
  "next_step": "Confirm to the customer that the order is cancelled.",
  "note": "Mock assessment system: only the demo database record changed. No real order or payment was affected."
}
```

Repeat attempt, `409`:

```json
{
  "order_id": "ORD-103",
  "cancelled": false,
  "outcome": "ALREADY_CANCELLED",
  "previous_status": "Cancelled",
  "status": "Cancelled",
  "cancelled_at": "2026-10-17T04:30:00+00:00",
  "reason": "ORD-103 was already cancelled.",
  "next_step": "Tell the customer it's already cancelled. Nothing more is needed.",
  "note": "Mock assessment system: only the demo database record changed. No real order or payment was affected."
}
```

ORD-101 returns `409` with `outcome: NOT_ELIGIBLE`. **Only treat an order as cancelled when `cancelled` is `true`.**

## Reason codes

| Check | Codes |
|---|---|
| cancellation | `STATUS_PROCESSING`, `STATUS_SHIPPED`, `STATUS_OUT_FOR_DELIVERY`, `STATUS_DELIVERED`, `ALREADY_CANCELLED`, `STATUS_UNKNOWN` |
| return | `REASON_MISSING`, `NOT_DELIVERED`, `OUTSIDE_RETURN_WINDOW`, `OPENED_UNKNOWN`, `OPENED_OR_USED`, `WITHIN_WINDOW_UNOPENED` |
| damage_claim | `NOT_DELIVERED`, `OUTSIDE_DAMAGE_WINDOW`, `PHOTOS_UNCONFIRMED`, `PHOTOS_REQUIRED`, `WITHIN_48_HOURS_WITH_PHOTOS` |
| shipping | `ABOVE_499`, `BELOW_499`, `EXACTLY_499` |
| cod | `WITHIN_COD_LIMIT`, `ABOVE_COD_LIMIT` |

## Errors

Every error has the same envelope: `{"error": {"code", "message", "order_id"?}}`. Messages are written to be safe to show or speak; they never contain stack traces, SQL or file paths.

| HTTP | `code` | When |
|---|---|---|
| 404 | `ORDER_NOT_FOUND` | Well-formed ID with no record |
| 404 | `NOT_FOUND` | Unknown route |
| 405 | `METHOD_NOT_ALLOWED` | e.g. `GET …/cancel` |
| 422 | `ORDER_ID_MISSING` | Empty or whitespace ID, or `GET /api/orders` |
| 422 | `ORDER_ID_INVALID` | Not an order ID (`ORD-1O1`, `abc`) |
| 422 | `VALIDATION_ERROR` | Bad body or query (wrong types, unknown fields, both or neither of `order_value`/`order_id`) |
| 503 | `DATABASE_UNAVAILABLE` | SQLite failure. Nothing was changed. |
| 500 | `INTERNAL_ERROR` | Anything unexpected |
| other | `HTTP_ERROR` | Any other HTTP-level error |

```json
{
  "error": {
    "code": "ORDER_NOT_FOUND",
    "message": "No order with ID ORD-999 exists. Ask the customer to repeat or verify the order number.",
    "order_id": "ORD-999"
  }
}
```

```json
{
  "error": {
    "code": "ORDER_ID_INVALID",
    "message": "'ORD-1O1' isn't a valid order ID. Order IDs look like ORD-101. Ask the customer to repeat or check it."
  }
}
```

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request: check opened."
  }
}
```

`/health` returns `{"status": "ok", "database": "ok"}` (`200`) or `{"status": "degraded", "database": "unavailable"}` (`503`).

## Voice calls (Phase 4)

These routes let the browser hold a Gemini Live voice call while the backend stays in charge of credentials and every order fact. The examples were captured from the real routes, with the test suite's fake token minter standing in for Google, so the token values are fake.

| Purpose | Method and path | Auth | Success |
|---|---|---|---|
| Start a call | `POST /api/voice/sessions` | — (rate-limited per IP) | `201` SessionCreated |
| Run a tool Aria asked for | `POST /api/voice/sessions/{session_id}/tool-calls` | `X-Session-Secret` header | `200` ToolCallResponse |
| End the call and summarise it | `POST /api/voice/sessions/{session_id}/end` | `X-Session-Secret` header | `200` EndCallResponse |

### Flow

1. The browser calls `POST /api/voice/sessions`. The backend mints a **single-use Gemini ephemeral token** (connect within 1 minute, valid for the call length, at most 15 minutes) and locks the model and the whole `live_config` into it. Gemini's API key never leaves the server.
2. The browser connects with `@google/genai`: `new GoogleGenAI({ apiKey: token, httpOptions: { apiVersion } })` and `ai.live.connect({ model, config: live_config })`, passing `live_config` unchanged.
3. When Gemini sends `toolCall.functionCalls`, the browser posts each call here and returns `response` **unchanged** via `session.sendToolResponse({ functionResponses: [{ id, name, response }] })`.
4. When the call ends, the browser posts the transcript to `/end` and shows the returned record.

### Start a call: `POST /api/voice/sessions`

`201`. `live_config` is abridged here:

```json
{
  "session_id": "052c927324aa4b0eb9a2e4b52fcad879",
  "session_secret": "c03BrEFuwwRQh930Ipne55oXLS0aU5fAFN9vpTcGd5U",
  "token": "auth_tokens/fake-1",
  "token_expires_at": "2026-10-17T04:45:00+00:00",
  "new_session_expires_at": "2026-10-17T04:31:00+00:00",
  "model": "gemini-3.8-live",
  "api_version": "v1beta",
  "live_config": "{…the Live config, about 8 KB: system instruction, 6 BLOCKING tools, voice, transcription, VAD…}",
  "call_connected_cue": "[call connected]"
}
```

Keep `session_secret` in memory only; it authorises this call's tool and end requests. The backend stores only its SHA-256 hash.

### Tool calls: `POST /api/voice/sessions/{session_id}/tool-calls`

Body: `{"call_id": "<Gemini function call id>", "name": "<tool>", "args": {...}}`. Unknown fields are rejected.

Tools: `get_order_details`, `check_cancellation_eligibility`, `cancel_order`, `check_return_eligibility`, `check_shipping`, `check_cod`. Their arguments mirror the REST endpoints above. All are declared to Gemini as `BLOCKING`, because `gemini-3.8-live` defaults to non-blocking calls, where the model keeps talking before the result arrives.

**`response` is always a JSON object for the model**, `{"ok": true, "result": ...}` or `{"ok": false, "error": {"code", "message"}}`, with HTTP `200` even when the tool failed. The model needs to hear about failures, not get nothing. HTTP errors are reserved for the session itself (403, 404, 409, 422).

Success:

```json
{
  "call_id": "fc-1",
  "name": "check_cancellation_eligibility",
  "response": {
    "ok": true,
    "result": {
      "check": "cancellation",
      "order_id": "ORD-103",
      "outcome": "ELIGIBLE",
      "reason_code": "STATUS_PROCESSING",
      "reason": "ORD-103 is still Processing, so it can be cancelled.",
      "next_step": "Confirm the customer wants to cancel, then call cancel_order. Don't say it's cancelled until cancel_order succeeds.",
      "policy": "Orders can be cancelled only while their status is Processing. Once an order is Shipped or Out for Delivery, it cannot be cancelled (customers may refuse delivery at doorstep).",
      "details": {
        "status": "Processing"
      },
      "eligible": true
    }
  }
}
```

Unknown order:

```json
{
  "call_id": "fc-2",
  "name": "get_order_details",
  "response": {
    "ok": false,
    "error": {
      "code": "ORDER_NOT_FOUND",
      "message": "No order with ID ORD-999 exists. Ask the customer to repeat or verify the order number."
    }
  }
}
```

Cancellation gate:

```json
{
  "call_id": "fc-3",
  "name": "cancel_order",
  "response": {
    "ok": false,
    "error": {
      "code": "CONFIRMATION_REQUIRED",
      "message": "Not cancelled. Ask the customer to confirm they want to cancel ORD-103, then call cancel_order with customer_confirmed true."
    }
  }
}
```

`cancel_order` only runs when **both** server-side gates pass:
- `customer_confirmed` is JSON `true`. Strings like `"yes"` and numbers are rejected as `INVALID_ARGUMENTS`.
- `check_cancellation_eligibility` returned `ELIGIBLE` for the same order **in the same session**.

`cancel_order` then re-checks the database itself, as in Phase 3.

| Tool error `code` | Meaning |
|---|---|
| `ORDER_NOT_FOUND`, `ORDER_ID_INVALID`, `ORDER_ID_MISSING` | As in the REST API |
| `INVALID_ARGUMENTS` | Missing, extra, mistyped or oversized (>2 KB) arguments |
| `UNKNOWN_TOOL` | No such tool |
| `CONFIRMATION_REQUIRED` | `cancel_order` without `customer_confirmed: true` |
| `ELIGIBILITY_NOT_CHECKED` | `cancel_order` without an `ELIGIBLE` check for that order in this call |
| `DATABASE_UNAVAILABLE` | SQLite failed; nothing was changed |
| `TOOL_UNAVAILABLE` | Produced **by the browser** when this endpoint can't be reached, so Aria says records are unavailable rather than guessing |

### End a call: `POST /api/voice/sessions/{session_id}/end`

Body: `{"transcript": [{"speaker": "customer"|"agent", "text": "..."}], "end_reason": "customer_ended"|"disconnected"|"error"|"timeout", "client_tool_failures": 0}`. The limits are 400 turns and 4,000 characters per turn.

The route is **idempotent**: repeating it returns the stored record unchanged, even if the new body differs.

```json
{
  "session_id": "052c927324aa4b0eb9a2e4b52fcad879",
  "transcript": [
    {
      "speaker": "agent",
      "text": "Hi, I'm Aria from Aura Skincare. How can I help?"
    },
    {
      "speaker": "customer",
      "text": "Please cancel my order ORD-103."
    },
    {
      "speaker": "agent",
      "text": "ORD-103 is still processing, so it can be cancelled. Shall I go ahead?"
    },
    {
      "speaker": "customer",
      "text": "Yes, please."
    },
    {
      "speaker": "agent",
      "text": "Done. ORD-103 has been cancelled."
    }
  ],
  "summary": {
    "session_id": "052c927324aa4b0eb9a2e4b52fcad879",
    "started_at": "2026-10-17T04:30:00+00:00",
    "ended_at": "2026-10-17T04:30:00+00:00",
    "duration_seconds": 0,
    "end_reason": "customer_ended",
    "customer_intent": "CANCELLATION",
    "customer_issue": "Please cancel my order ORD-103.",
    "order_id": "ORD-103",
    "order_ids": [
      "ORD-103"
    ],
    "actions_taken": [
      {
        "tool": "check_cancellation_eligibility",
        "order_id": "ORD-103",
        "ok": true,
        "outcome": "ELIGIBLE",
        "at": "2026-10-17T04:30:00+00:00",
        "reason_code": "STATUS_PROCESSING",
        "check": "cancellation"
      },
      {
        "tool": "get_order_details",
        "order_id": "ORD-999",
        "ok": false,
        "outcome": "ORDER_NOT_FOUND",
        "at": "2026-10-17T04:30:00+00:00",
        "error_code": "ORDER_NOT_FOUND"
      },
      {
        "tool": "cancel_order",
        "order_id": "ORD-103",
        "ok": false,
        "outcome": "CONFIRMATION_REQUIRED",
        "at": "2026-10-17T04:30:00+00:00",
        "error_code": "CONFIRMATION_REQUIRED"
      },
      {
        "tool": "cancel_order",
        "order_id": "ORD-103",
        "ok": true,
        "outcome": "CANCELLED",
        "at": "2026-10-17T04:30:00+00:00",
        "cancelled": true
      }
    ],
    "resolution_status": "RESOLVED",
    "final_outcome": "Order cancelled at the customer's request. Aria answered using order records and policy checks.",
    "follow_up_required": false,
    "follow_up_reasons": [],
    "unresolved_issues": [],
    "call_summary": "cancellation check for ORD-103: ELIGIBLE (STATUS_PROCESSING). Order lookup failed (ORDER_NOT_FOUND) for ORD-999. cancel_order failed (CONFIRMATION_REQUIRED). ORD-103 cancelled.",
    "transcript_turns": 5,
    "summary_source": "rules: built from tools this server executed and the call transcript; no AI-written text"
  }
}
```

How the summary is built:
- It is built by rules from this server's own tool log, so `actions_taken`, `order_id` and outcomes only ever reflect tools that actually ran. `customer_issue` is the customer's first transcribed utterance, quoted verbatim.
- `customer_intent` is one of `ORDER_TRACKING`, `CANCELLATION`, `RETURN_REFUND`, `DAMAGED_OR_DEFECTIVE`, `SHIPPING_QUESTION`, `COD_QUESTION`, `GENERAL_INQUIRY` or `NO_CONVERSATION`.
- `end_reason` is the reason the browser sent: `customer_ended`, `disconnected`, `timeout` or `error`.
- `resolution_status` is one of `RESOLVED`, `POLICY_DECLINED`, `NEEDS_FOLLOW_UP` (tool failures, a policy that doesn't cover the case such as ₹499 shipping, or a call with conversation that ended unexpectedly: `disconnected`, `timeout` or `error`), `NOT_DETERMINED` (nothing on record shows how it ended, e.g. no tool was used, or an order was never found) or `NO_CONVERSATION`.

### Voice errors

| HTTP | `code` | When |
|---|---|---|
| 503 | `VOICE_NOT_CONFIGURED` | `GEMINI_API_KEY` isn't set |
| 502 | `VOICE_PROVIDER_ERROR` | Google refused or failed to mint a token (details are logged as an error type only) |
| 429 | `RATE_LIMITED` | Too many new calls from this client IP in the last hour |
| 403 | `SESSION_FORBIDDEN` | Missing or wrong `X-Session-Secret` |
| 404 | `SESSION_NOT_FOUND` | Unknown session ID |
| 409 | `SESSION_ENDED` / `SESSION_EXPIRED` | Tool call after the call ended, or more than 5 minutes after its token expired |

```json
{
  "error": {
    "code": "VOICE_NOT_CONFIGURED",
    "message": "Voice calling isn't set up on this server yet (no Gemini API key)."
  }
}
```

```json
{
  "error": {
    "code": "SESSION_FORBIDDEN",
    "message": "Missing or wrong session secret."
  }
}
```

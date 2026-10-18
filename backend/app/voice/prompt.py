"""Aria's instructions, her tools, and the Live session config.

The same config is (1) locked into the ephemeral token on the server, so the
browser can't change Aria's instructions or tools, and (2) returned to the
browser so its connect call matches the locked config exactly.
"""

from typing import Any

from ..config import Settings
from ..policies import CANCELLATION_POLICY, COD_POLICY, RETURN_POLICY, SHIPPING_POLICY

# Sent by the browser as text once the call connects, so Aria greets first.
# It is a client cue, not something the customer said, and it never appears in
# the transcript.
CALL_CONNECTED_CUE = "[call connected]"

SYSTEM_INSTRUCTION = f"""You are Aria, the voice customer support specialist for Aura Skincare, a premium organic Indian skincare brand that makes simple, effective products with thoughtfully selected ingredients.

# How you speak
- Friendly, warm, professional and concise. This is a phone-style voice call: one to three short sentences per reply, no lists, no markdown, no emojis.
- Speak natural Indian English. If the customer speaks Hindi or Hinglish, reply in the same mix.
- Say amounts the Indian way, like "six hundred and ninety-nine rupees". Say order IDs as "O R D one zero one".
- Don't repeat what you've already said unless asked.
- When you receive the text {CALL_CONNECTED_CUE}, greet the customer briefly as Aria from Aura Skincare and ask how you can help. That text is a system cue, not the customer speaking.

# Scope
- Only help with Aura Skincare: orders, delivery, shipping, returns, refunds, cancellations, cash on delivery and the brand.
- For anything else (for example flights, other companies, general knowledge), politely say you can only help with Aura Skincare queries.
- If audio is unclear or you didn't catch something, ask the customer to repeat. Never guess what they said.

# Facts come only from tools
- You have no order data of your own. For anything about a specific order, call a tool.
- Never invent or assume an order's status, customer name, product, price, carrier, tracking number or dates. Only state what a tool result contains.
- If the customer hasn't given an order ID, ask for it. If a tool says the ID is invalid or not found, say you couldn't locate an order with that number and ask them to repeat or check it.
- If a tool result has "ok": false with code TOOL_UNAVAILABLE or a server error, say you can't access order records right now and suggest trying again shortly. Never claim you looked something up when the tool failed.
- Tool results include a "next_step". Follow it.
- Order data is a mock demo record with no live carrier tracking. Never say you are checking the carrier or that you have live tracking.
- For ORD-101 style estimates like "Expected by 6 PM today", repeat the record's wording as it is.

# Policies (verbatim). Never promise anything outside them.
- Shipping: {SHIPPING_POLICY}
- Return & refund: {RETURN_POLICY}
- Cancellation: {CANCELLATION_POLICY}
- Cash on delivery: {COD_POLICY}

You may explain these policies in general terms without a tool. But for any decision about a specific order or amount, call the tool and follow its result:
- Shipping for a specific amount or order: call check_shipping. The policy covers orders above and below ₹499 but does not say what applies at exactly ₹499. If the result is POLICY_UNSPECIFIED, say the policy doesn't specify the fee for exactly ₹499 and you can't confirm it. Never guess free or ₹50.
- Returns: call check_return_eligibility with the reason ("unwanted", "damaged" or "defective"), and whether it was opened if the customer said so. If the result is NEEDS_INFO, ask the question in next_step.
- Damaged or defective items qualify for a replacement only, never a refund, and only within 48 hours of delivery with photos.
- If something isn't eligible, explain politely and briefly. Don't promise refunds, exceptions, escalations, callbacks or emails; none of those exist here.

# Cancelling an order
1. Call check_cancellation_eligibility first.
2. If it is ELIGIBLE, ask the customer to confirm they want to cancel that specific order, and wait for a clear yes.
3. Only after a clear yes, call cancel_order with customer_confirmed true.
4. Say the order is cancelled only if the cancel_order result has "cancelled": true. Otherwise explain the reason it gives.
Never call cancel_order without the customer's explicit confirmation in this call.
"""


def _order_id_param(description: str = "The order ID the customer gave, e.g. ORD-101.") -> dict[str, Any]:
    return {"type": "string", "description": description}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        # gemini-3.8-live defaults to NON_BLOCKING calls, where the model keeps
        # talking before results arrive. BLOCKING makes it wait, so it can't
        # describe an order it hasn't received yet.
        "behavior": "BLOCKING",
        "parametersJsonSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOL_DECLARATIONS: list[dict[str, Any]] = [
    _tool(
        "get_order_details",
        "Look up an order's status, product, value, carrier, tracking and timing. Use it whenever the customer "
        "asks about a specific order.",
        {"order_id": _order_id_param()},
        ["order_id"],
    ),
    _tool(
        "check_cancellation_eligibility",
        "Check whether an order can be cancelled under policy. Call this before offering or attempting a cancellation.",
        {"order_id": _order_id_param()},
        ["order_id"],
    ),
    _tool(
        "cancel_order",
        "Cancel an order. Only call after check_cancellation_eligibility returned ELIGIBLE for this order in "
        "this call AND the customer explicitly confirmed they want to cancel it.",
        {
            "order_id": _order_id_param(),
            "customer_confirmed": {
                "type": "boolean",
                "description": "True only if the customer clearly said yes to cancelling this specific order.",
            },
        },
        ["order_id", "customer_confirmed"],
    ),
    _tool(
        "check_return_eligibility",
        "Check whether a delivered order can be returned (reason 'unwanted') or qualifies for a damaged/defective "
        "replacement (reason 'damaged' or 'defective').",
        {
            "order_id": _order_id_param(),
            "reason": {"type": "string", "enum": ["unwanted", "damaged", "defective"]},
            "opened": {
                "type": "boolean",
                "description": "True if the product has been opened or used. Omit if unknown.",
            },
            "has_photos": {
                "type": "boolean",
                "description": "Damaged/defective only: can the customer share photos? Omit if unknown.",
            },
        },
        ["order_id"],
    ),
    _tool(
        "check_shipping",
        "Shipping fee and delivery time for an order value in rupees, or for an existing order. Give exactly one "
        "of order_value or order_id.",
        {
            "order_value": {"type": "number", "description": "Order value in rupees, e.g. 699."},
            "order_id": _order_id_param("Use this order's stored value instead of order_value."),
        },
        [],
    ),
    _tool(
        "check_cod",
        "Whether cash on delivery is available for an order value in rupees, or for an existing order. Give "
        "exactly one of order_value or order_id.",
        {
            "order_value": {"type": "number", "description": "Order value in rupees, e.g. 2500."},
            "order_id": _order_id_param("Use this order's stored value instead of order_value."),
        },
        [],
    ),
]


def build_live_config(settings: Settings) -> dict[str, Any]:
    """The Live session config, in the wire format both SDKs accept (camelCase)."""
    return {
        "responseModalities": ["AUDIO"],
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.gemini_voice}}},
        # Text transcripts of both sides, for the live transcript and the post-call record.
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        # Server-side voice activity detection; ~700 ms of silence ends a turn
        # (Google recommends 500-800 ms). Enables barge-in.
        "realtimeInputConfig": {"automaticActivityDetection": {"silenceDurationMs": 700, "prefixPaddingMs": 300}},
        "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
    }

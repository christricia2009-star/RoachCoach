"""
Roach Coach Radar — Payments (Phase 5)

Thin, provider-agnostic wrapper around Stripe and Square so main.py's
order endpoints don't need to know which processor is configured.

Design:
    - Orders are always created unpaid (see main.py's create_order).
    - The client then asks this module (via a main.py endpoint) to start
      a payment against that order's already-server-computed total_cents.
      Never trust a client-submitted amount here either.
    - Stripe: PaymentIntent + client_secret, confirmed client-side with
      Stripe.js / PaymentSheet. Server truth arrives via webhook.
    - Square: Payments API, charged synchronously server-side from a
      one-time card nonce (`sourceId`) produced by the Square Web
      Payments SDK / In-App Payments SDK. Square also sends webhooks
      for async updates (disputes, refunds), handled below.

Which provider is "active" is controlled by PAYMENT_PROVIDER (stripe |
square), but both SDKs stay wired so a truck-by-truck or A/B switch is
just a config change, not a code change.
"""

from __future__ import annotations

import os
from typing import Any, Optional

DEFAULT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "stripe").strip().lower()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID")
SQUARE_APPLICATION_ID = os.getenv("SQUARE_APPLICATION_ID")
SQUARE_WEBHOOK_SIGNATURE_KEY = os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY")
SQUARE_ENVIRONMENT = os.getenv("SQUARE_ENVIRONMENT", "sandbox").strip().lower()


class PaymentError(Exception):
    """Raised for any provider-side failure; main.py turns this into a 4xx/5xx."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _stripe_sdk_available() -> bool:
    try:
        import stripe  # noqa: F401
        return True
    except ImportError:
        return False


def public_config() -> dict[str, Any]:
    """Non-secret config the frontend needs to initialize a payment SDK."""

    stripe_ready = bool(STRIPE_SECRET_KEY) and _stripe_sdk_available()
    return {
        "provider": DEFAULT_PROVIDER,
        "stripe": {
            "enabled": stripe_ready,
            "publishableKey": STRIPE_PUBLISHABLE_KEY if stripe_ready else None,
        },
        "square": {
            "enabled": bool(SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID),
            "applicationId": SQUARE_APPLICATION_ID,
            "locationId": SQUARE_LOCATION_ID,
            "environment": SQUARE_ENVIRONMENT,
        },
    }


# ============================================================
# STRIPE
# ============================================================

def _stripe_client():
    if not STRIPE_SECRET_KEY:
        raise PaymentError("Stripe is not configured (STRIPE_SECRET_KEY missing)", status_code=500)
    try:
        import stripe
    except ImportError as exc:
        raise PaymentError(f"stripe package not installed: {exc}", status_code=500)
    stripe.api_key = STRIPE_SECRET_KEY
    stripe.max_network_retries = 2
    return stripe


def stripe_create_payment_intent(
    order_id: str,
    amount_cents: int,
    currency: str = "usd",
    customer_name: Optional[str] = None,
    existing_intent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Creates (or, if one already exists for this order, updates) a
    PaymentIntent for the exact server-computed order total. Returns the
    fields main.py needs to hand back to the client and to persist on
    the order record."""

    if amount_cents <= 0:
        raise PaymentError("Order total must be greater than zero to charge", status_code=400)

    stripe = _stripe_client()

    metadata = {"order_id": order_id}
    idempotency_key = f"order_{order_id}_intent"

    try:
        if existing_intent_id:
            intent = stripe.PaymentIntent.modify(
                existing_intent_id,
                amount=amount_cents,
                currency=currency,
                metadata=metadata,
            )
        else:
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                automatic_payment_methods={"enabled": True},
                metadata=metadata,
                description=f"Roach Coach order {order_id}"
                + (f" for {customer_name}" if customer_name else ""),
                idempotency_key=idempotency_key,
            )
    except Exception as exc:  # stripe.error.StripeError and friends
        raise PaymentError(f"Stripe PaymentIntent failed: {exc}")

    return {
        "provider": "stripe",
        "paymentIntentId": intent["id"],
        "clientSecret": intent["client_secret"],
        "status": intent["status"],
        "amountCents": intent["amount"],
        "currency": intent["currency"],
    }


def stripe_retrieve_intent(payment_intent_id: str) -> dict[str, Any]:
    stripe = _stripe_client()
    try:
        return stripe.PaymentIntent.retrieve(payment_intent_id)
    except Exception as exc:
        raise PaymentError(f"Stripe PaymentIntent lookup failed: {exc}")


def stripe_refund(payment_intent_id: str, amount_cents: Optional[int] = None) -> dict[str, Any]:
    stripe = _stripe_client()
    try:
        kwargs: dict[str, Any] = {"payment_intent": payment_intent_id}
        if amount_cents is not None:
            kwargs["amount"] = amount_cents
        refund = stripe.Refund.create(**kwargs)
    except Exception as exc:
        raise PaymentError(f"Stripe refund failed: {exc}")
    return {"provider": "stripe", "refundId": refund["id"], "status": refund["status"]}


# Maps a Stripe PaymentIntent status onto our own payment_status vocabulary
# (unpaid | authorized | captured | refunded | failed — see schema.sql).
_STRIPE_STATUS_MAP = {
    "requires_payment_method": "unpaid",
    "requires_confirmation": "unpaid",
    "requires_action": "unpaid",
    "processing": "authorized",
    "requires_capture": "authorized",
    "succeeded": "captured",
    "canceled": "failed",
}


def stripe_status_to_order_status(stripe_status: str) -> str:
    return _STRIPE_STATUS_MAP.get(stripe_status, "unpaid")


def stripe_verify_webhook(payload: bytes, sig_header: Optional[str]):
    """Verifies the Stripe-Signature header and returns the parsed event.
    Raises PaymentError (400) on a bad/missing signature — callers should
    return that as the HTTP status so Stripe's retry logic behaves."""

    stripe = _stripe_client()
    if not STRIPE_WEBHOOK_SECRET:
        raise PaymentError("STRIPE_WEBHOOK_SECRET is not configured", status_code=500)
    if not sig_header:
        raise PaymentError("Missing Stripe-Signature header", status_code=400)
    try:
        return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError as exc:
        raise PaymentError(f"Invalid webhook payload: {exc}", status_code=400)
    except Exception as exc:  # stripe.error.SignatureVerificationError
        raise PaymentError(f"Invalid webhook signature: {exc}", status_code=400)


# ============================================================
# SQUARE
# ============================================================

def _square_client():
    if not (SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID):
        raise PaymentError(
            "Square is not configured (SQUARE_ACCESS_TOKEN/SQUARE_LOCATION_ID missing)",
            status_code=500,
        )
    try:
        from square.client import Client as SquareClient
    except ImportError as exc:
        raise PaymentError(f"squareup package not installed: {exc}", status_code=500)

    return SquareClient(
        access_token=SQUARE_ACCESS_TOKEN,
        environment="production" if SQUARE_ENVIRONMENT == "production" else "sandbox",
    )


def square_charge(
    order_id: str,
    amount_cents: int,
    source_id: str,
    currency: str = "USD",
    customer_name: Optional[str] = None,
    verification_token: Optional[str] = None,
) -> dict[str, Any]:
    """Charges a one-time card `source_id` (nonce) from the Square Web
    Payments SDK for the exact server-computed order total. Square
    payments are synchronous — the result is known before this returns,
    unlike Stripe's confirm-then-webhook flow."""

    if amount_cents <= 0:
        raise PaymentError("Order total must be greater than zero to charge", status_code=400)

    client = _square_client()

    body: dict[str, Any] = {
        "source_id": source_id,
        "idempotency_key": f"order_{order_id}_charge",
        "amount_money": {"amount": amount_cents, "currency": currency},
        "location_id": SQUARE_LOCATION_ID,
        "note": f"Roach Coach order {order_id}" + (f" for {customer_name}" if customer_name else ""),
        "reference_id": order_id,
    }
    if verification_token:
        body["verification_token"] = verification_token

    result = client.payments.create_payment(body=body)

    if result.is_error():
        detail = "; ".join(e.get("detail", str(e)) for e in result.errors)
        raise PaymentError(f"Square payment failed: {detail}", status_code=402)

    payment = result.body.get("payment", {})
    return {
        "provider": "square",
        "paymentId": payment.get("id"),
        "status": payment.get("status"),  # APPROVED | COMPLETED | FAILED | CANCELED
        "amountCents": payment.get("amount_money", {}).get("amount"),
        "currency": payment.get("amount_money", {}).get("currency"),
        "receiptUrl": payment.get("receipt_url"),
    }


def square_refund(payment_id: str, amount_cents: int, currency: str = "USD", order_id: str = "") -> dict[str, Any]:
    client = _square_client()
    body = {
        "idempotency_key": f"order_{order_id}_refund",
        "amount_money": {"amount": amount_cents, "currency": currency},
        "payment_id": payment_id,
    }
    result = client.refunds.refund_payment(body=body)
    if result.is_error():
        detail = "; ".join(e.get("detail", str(e)) for e in result.errors)
        raise PaymentError(f"Square refund failed: {detail}", status_code=402)
    refund = result.body.get("refund", {})
    return {"provider": "square", "refundId": refund.get("id"), "status": refund.get("status")}


_SQUARE_STATUS_MAP = {
    "APPROVED": "authorized",
    "COMPLETED": "captured",
    "FAILED": "failed",
    "CANCELED": "failed",
}


def square_status_to_order_status(square_status: str) -> str:
    return _SQUARE_STATUS_MAP.get(square_status, "unpaid")


def square_verify_webhook(payload: bytes, signature: Optional[str], notification_url: str) -> None:
    """Verifies Square's HMAC-SHA256 webhook signature. Raises
    PaymentError(400) on failure. Square's scheme signs
    notification_url + raw_body, unlike Stripe's timestamp+payload
    scheme, so this needs the exact URL Square was configured with."""

    import base64
    import hashlib
    import hmac

    if not SQUARE_WEBHOOK_SIGNATURE_KEY:
        raise PaymentError("SQUARE_WEBHOOK_SIGNATURE_KEY is not configured", status_code=500)
    if not signature:
        raise PaymentError("Missing x-square-hmacsha256-signature header", status_code=400)

    digest = hmac.new(
        SQUARE_WEBHOOK_SIGNATURE_KEY.encode("utf-8"),
        msg=(notification_url.encode("utf-8") + payload),
        digestmod=hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")

    if not hmac.compare_digest(expected, signature):
        raise PaymentError("Invalid Square webhook signature", status_code=400)

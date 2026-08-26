"""
Phase 3: delivery-app pickup-pin data (Uber Eats / DoorDash), per your
existing written partnerships in your test area.

Neither platform exposes this publicly — it only exists here because of
those agreements. Every partner integration is bespoke: this is a generic
polling pattern using each platform's typical partner-API auth style
(OAuth2 client-credentials is common for both), NOT a working integration
for any specific account — swap in the real endpoint paths and field names
from the partnership docs Uber/DoorDash actually gave you.

Scope this the same way as the telecom module: only poll for trucks/
merchants actually covered by your written agreements, not broadly.
"""

import os
import time
import requests
from dataclasses import dataclass
from typing import Optional
import datetime

UBER_CLIENT_ID = os.getenv("UBER_PARTNER_CLIENT_ID", "")
UBER_CLIENT_SECRET = os.getenv("UBER_PARTNER_CLIENT_SECRET", "")
UBER_API_BASE_URL = os.getenv("UBER_PARTNER_API_BASE_URL", "")

DOORDASH_API_KEY = os.getenv("DOORDASH_PARTNER_API_KEY", "")
DOORDASH_API_BASE_URL = os.getenv("DOORDASH_PARTNER_API_BASE_URL", "")

# Merchant/store IDs your written partnerships actually cover. Populate
# with the real IDs your Uber/DoorDash partner contacts gave you — this
# should never be a broad "every merchant" pull.
AGREED_UBER_MERCHANT_IDS: list[str] = []
AGREED_DOORDASH_STORE_IDS: list[str] = []


@dataclass
class PickupPin:
    platform: str  # "uber" | "doordash"
    merchant_id: str
    merchant_name: str
    latitude: float
    longitude: float
    reported_at: datetime.datetime


_uber_token_cache: dict = {"token": None, "expires_at": 0}


def _get_uber_access_token() -> str:
    """
    OAuth2 client-credentials flow — typical pattern for Uber's partner
    APIs. Confirm the actual token endpoint and scopes with your Uber
    partnership contact; this is the standard shape, not a confirmed
    working endpoint.
    """
    if _uber_token_cache["token"] and time.time() < _uber_token_cache["expires_at"]:
        return _uber_token_cache["token"]

    if not UBER_CLIENT_ID or not UBER_CLIENT_SECRET or not UBER_API_BASE_URL:
        raise RuntimeError(
            "UBER_PARTNER_CLIENT_ID / UBER_PARTNER_CLIENT_SECRET / "
            "UBER_PARTNER_API_BASE_URL not set — fill in from your Uber "
            "partnership docs."
        )

    response = requests.post(
        f"{UBER_API_BASE_URL}/oauth/v2/token",
        data={
            "client_id": UBER_CLIENT_ID,
            "client_secret": UBER_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    _uber_token_cache["token"] = payload["access_token"]
    _uber_token_cache["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
    return _uber_token_cache["token"]


def fetch_uber_pickup_pins() -> list[PickupPin]:
    """
    ADJUST the endpoint path and response field names to match your actual
    Uber partnership API docs — this is illustrative, not confirmed.
    """
    if not AGREED_UBER_MERCHANT_IDS:
        raise RuntimeError(
            "AGREED_UBER_MERCHANT_IDS is empty — populate it with the "
            "merchant IDs your Uber partnership actually covers."
        )

    token = _get_uber_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    pins = []
    for merchant_id in AGREED_UBER_MERCHANT_IDS:
        response = requests.get(
            f"{UBER_API_BASE_URL}/v1/merchants/{merchant_id}/current-location",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        pins.append(
            PickupPin(
                platform="uber",
                merchant_id=merchant_id,
                merchant_name=data.get("name", "Unknown"),
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
                reported_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )
    return pins


def fetch_doordash_pickup_pins() -> list[PickupPin]:
    """
    ADJUST the endpoint path and response field names to match your actual
    DoorDash partnership API docs — this is illustrative, not confirmed.
    """
    if not AGREED_DOORDASH_STORE_IDS:
        raise RuntimeError(
            "AGREED_DOORDASH_STORE_IDS is empty — populate it with the "
            "store IDs your DoorDash partnership actually covers."
        )
    if not DOORDASH_API_KEY or not DOORDASH_API_BASE_URL:
        raise RuntimeError(
            "DOORDASH_PARTNER_API_KEY / DOORDASH_PARTNER_API_BASE_URL not "
            "set — fill in from your DoorDash partnership docs."
        )

    headers = {"Authorization": f"Bearer {DOORDASH_API_KEY}"}
    pins = []
    for store_id in AGREED_DOORDASH_STORE_IDS:
        response = requests.get(
            f"{DOORDASH_API_BASE_URL}/v1/stores/{store_id}/location",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        pins.append(
            PickupPin(
                platform="doordash",
                merchant_id=store_id,
                merchant_name=data.get("business_name", "Unknown"),
                latitude=float(data["lat"]),
                longitude=float(data["lng"]),
                reported_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )
    return pins


def fetch_all_pickup_pins() -> list[PickupPin]:
    pins: list[PickupPin] = []
    try:
        pins.extend(fetch_uber_pickup_pins())
    except Exception as e:
        print(f"Uber pickup pin fetch failed: {e}")
    try:
        pins.extend(fetch_doordash_pickup_pins())
    except Exception as e:
        print(f"DoorDash pickup pin fetch failed: {e}")
    return pins


if __name__ == "__main__":
    print(
        "Populate AGREED_UBER_MERCHANT_IDS / AGREED_DOORDASH_STORE_IDS and "
        "the relevant API credentials from your partnership docs to test "
        "this module."
    )

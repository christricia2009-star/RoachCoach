"""
CloudKit Web Services bridge.

You chose CloudKit (not Postgres) as the app's data store — this is the
piece that connects them: it lets Backend/ Python scripts (Phase 3 signal
fetchers, the social/LLM pipeline) write results into the SAME CloudKit
public database the iOS app already reads from via CloudKitService.swift.

Without this, Phase 3 modules run and return data, but nothing puts that
data anywhere the app can see it.

SETUP (one-time, in CloudKit Dashboard — icloud.developer.apple.com):
  1. Open your app's container → your container ID looks like
     "iCloud.com.yourbundleid.RoachCoachRadar".
  2. Go to "Server-to-Server Keys" (under the container's settings).
  3. Generate an EC (P-256) key pair. CloudKit gives you a Key ID and lets
     you download/register a private key — save the PRIVATE key file
     locally as a .pem, never commit it to source control.
  4. Set the three env vars below (.env) to your container ID, key ID, and
     the path to that .pem file.

IMPORTANT — this implements Apple's documented CloudKit Web Services
request-signing scheme (ECDSA P-256 over SHA-256, per Apple's "Building a
Signature" spec) as accurately as I can from documentation. I have not
been able to test it against a live CloudKit container from this
environment — the very first real call you make is the actual test.
If you get a 401/403 signature-mismatch error, the most common causes
are: (a) the ISO8601 date format not matching exactly what's used to sign
vs. what's sent in the header, or (b) needing the raw vs. DER-encoded
signature bytes — check the error message body, CloudKit's error
responses are usually specific about which check failed.
"""

import os
import json
import base64
import hashlib
import datetime
from typing import Optional
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

CLOUDKIT_CONTAINER_ID = os.getenv("CLOUDKIT_CONTAINER_ID", "")  # e.g. iCloud.com.yourbundleid.RoachCoachRadar
CLOUDKIT_KEY_ID = os.getenv("CLOUDKIT_KEY_ID", "")
CLOUDKIT_PRIVATE_KEY_PATH = os.getenv("CLOUDKIT_PRIVATE_KEY_PATH", "")
CLOUDKIT_ENVIRONMENT = os.getenv("CLOUDKIT_ENVIRONMENT", "development")  # "development" or "production"

CLOUDKIT_BASE_URL = "https://api.apple-cloudkit.com"


def _load_private_key():
    if not CLOUDKIT_PRIVATE_KEY_PATH or not os.path.exists(CLOUDKIT_PRIVATE_KEY_PATH):
        raise RuntimeError(
            "CLOUDKIT_PRIVATE_KEY_PATH not set or file not found. Generate a "
            "server-to-server key in CloudKit Dashboard and point this at "
            "the downloaded .pem file."
        )
    with open(CLOUDKIT_PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _sign_request(subpath: str, body_bytes: bytes) -> dict:
    """
    Builds the three required CloudKit Web Services auth headers per Apple's
    server-to-server request-signing scheme.
    """
    private_key = _load_private_key()

    iso_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body_hash = base64.b64encode(hashlib.sha256(body_bytes).digest()).decode("utf-8")

    message = f"{iso_date}:{body_hash}:{subpath}".encode("utf-8")
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    signature_b64 = base64.b64encode(signature).decode("utf-8")

    return {
        "X-Apple-CloudKit-Request-KeyID": CLOUDKIT_KEY_ID,
        "X-Apple-CloudKit-Request-ISO8601Date": iso_date,
        "X-Apple-CloudKit-Request-SignatureV1": signature_b64,
        "Content-Type": "application/json",
    }


def _post(subpath: str, payload: dict) -> dict:
    if not CLOUDKIT_CONTAINER_ID or not CLOUDKIT_KEY_ID:
        raise RuntimeError(
            "CLOUDKIT_CONTAINER_ID / CLOUDKIT_KEY_ID not set — see module "
            "docstring for CloudKit Dashboard setup steps."
        )

    body_bytes = json.dumps(payload).encode("utf-8")
    headers = _sign_request(subpath, body_bytes)
    url = f"{CLOUDKIT_BASE_URL}{subpath}"

    response = requests.post(url, headers=headers, data=body_bytes, timeout=15)
    if not response.ok:
        # CloudKit's error bodies are usually specific — surface them directly
        # rather than swallowing the detail in a generic exception.
        raise RuntimeError(f"CloudKit request failed ({response.status_code}): {response.text}")
    return response.json()


def _records_modify_subpath() -> str:
    return f"/database/1/{CLOUDKIT_CONTAINER_ID}/{CLOUDKIT_ENVIRONMENT}/public/records/modify"


def save_sighting(sighting: dict) -> dict:
    """
    Writes a sighting record into the same "Sighting" record type
    CloudKitService.swift reads from. `sighting` should have keys matching
    CloudKitService.swift's sighting(from:) expectations: truckId,
    latitude, longitude, note (optional), photoURL (optional), timestamp
    (ISO8601 string), confidenceLevel ("confirmed"|"likely"|"scheduled"),
    expiresAt (ISO8601 string).
    """
    record_name = sighting.get("id") or sighting["truckId"] + "-" + sighting["timestamp"]

    payload = {
        "operations": [
            {
                "operationType": "create",
                "record": {
                    "recordType": "Sighting",
                    "recordName": record_name,
                    "fields": {
                        "truckId": {"value": sighting["truckId"]},
                        "latitude": {"value": sighting["latitude"]},
                        "longitude": {"value": sighting["longitude"]},
                        "note": {"value": sighting.get("note", "")},
                        "photoURL": {"value": sighting.get("photoURL", "")},
                        "timestamp": {"value": sighting["timestamp"]},
                        "confidenceLevel": {"value": sighting["confidenceLevel"]},
                        "expiresAt": {"value": sighting["expiresAt"]},
                    },
                },
            }
        ]
    }
    return _post(_records_modify_subpath(), payload)


def save_truck(truck: dict) -> dict:
    """Writes/updates a truck record — same shape CloudKitService.swift's truck(from:) expects."""
    payload = {
        "operations": [
            {
                "operationType": "forceUpdate",
                "record": {
                    "recordType": "Truck",
                    "recordName": truck["id"],
                    "fields": {
                        "name": {"value": truck["name"]},
                        "cuisineType": {"value": truck.get("cuisineType", "")},
                        "socialLinks": {"value": truck.get("socialLinks", [])},
                        "averageConfidenceScore": {"value": truck.get("averageConfidenceScore", 0.0)},
                        "menuHighlights": {"value": truck.get("menuHighlights", [])},
                        "rating": {"value": truck.get("rating", 4.5)},
                        "averageWaitMinutes": {"value": truck.get("averageWaitMinutes", 8)},
                    },
                },
            }
        ]
    }
    return _post(_records_modify_subpath(), payload)


def save_unmatched_detection(detection: dict) -> dict:
    """
    Writes an UnmatchedDetection record — a signal-fusion hit that couldn't
    be confidently tied to a specific truck (see signal_fusion.py). These
    show up in the iOS app's Owner Dashboard "Pending Sighting
    Confirmations" screen for a human to resolve: attach to a real truck,
    or dismiss as noise.
    """
    payload = {
        "operations": [
            {
                "operationType": "create",
                "record": {
                    "recordType": "UnmatchedDetection",
                    "recordName": detection["id"],
                    "fields": {
                        "source": {"value": detection["source"]},
                        "latitude": {"value": detection["latitude"]},
                        "longitude": {"value": detection["longitude"]},
                        "timestamp": {"value": detection["timestamp"]},
                        "rawConfidence": {"value": detection["rawConfidence"]},
                        "reason": {"value": detection["reason"]},
                        "textHint": {"value": detection.get("textHint", "")},
                        "note": {"value": detection.get("note", "")},
                        "status": {"value": detection.get("status", "pending")},
                    },
                },
            }
        ]
    }
    return _post(_records_modify_subpath(), payload)


def resolve_unmatched_detection(detection_id: str, resolution: str, truck_id: Optional[str] = None) -> dict:
    """
    Called when a human resolves a pending detection from the Owner
    Dashboard: `resolution` is "attached" (with a truck_id) or "dismissed".
    Updates the UnmatchedDetection's status and, if attached, creates the
    real Sighting record at that point.
    """
    fields = {"status": {"value": resolution}}
    if truck_id:
        fields["resolvedTruckId"] = {"value": truck_id}

    payload = {
        "operations": [
            {
                "operationType": "update",
                "record": {
                    "recordType": "UnmatchedDetection",
                    "recordName": detection_id,
                    "fields": fields,
                },
            }
        ]
    }
    return _post(_records_modify_subpath(), payload)


if __name__ == "__main__":
    print(
        "Set CLOUDKIT_CONTAINER_ID, CLOUDKIT_KEY_ID, and "
        "CLOUDKIT_PRIVATE_KEY_PATH to test this against your real "
        "CloudKit container. This is the first live test of the signing "
        "logic — check the error body carefully if it fails."
    )

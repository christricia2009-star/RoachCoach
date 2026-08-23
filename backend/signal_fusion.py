"""
Signal fusion engine.

This is the missing piece between "Phase 3 modules return data" and
"CloudKit has a Sighting tied to the right Truck." Every source (camera
vision, telecom anomaly, delivery pickup pin, social caption) produces a
RawDetection in a common shape. This module decides, per detection:

  1. Can we confidently attach it to a specific known Truck? -> write a
     real Sighting record straight away.
  2. Do multiple independent sources agree on the same truck/place/time? ->
     that corroboration alone can push an otherwise-uncertain detection
     over the confidence line.
  3. Otherwise -> write an UnmatchedDetection record instead of guessing.
     A human (you, or eventually a truck owner) resolves it via the Owner
     Dashboard's "Pending Sighting Confirmations" screen — which is now
     wired to read real data instead of being a stub.

This is the actual implementation of the "signal fusion" idea from
PHASE3_ARCHITECTURE.md — the point of running multiple signal sources was
always to let them corroborate each other, not just to have more sources.
"""

import uuid
import math
import datetime
from dataclasses import dataclass, field
from typing import Optional

import cloudkit_bridge

# ---------- Config: how detections map to known trucks ----------

# Direct ID mappings — the highest-confidence match type, since there's no
# ambiguity at all. Populate as you learn the real IDs:
#   - Delivery platform merchant/store ID -> Truck ID (exact, e.g. from
#     your Uber/DoorDash partnership's merchant records)
#   - Telecom sector ID -> Truck ID, ONLY if a sector is small enough that
#     a spike there reliably means one specific truck (usually only true
#     for a truck's typical/exclusive parking spot)
DIRECT_ID_MAPPINGS: dict[str, str] = {
    # "uber:merchant_12345": "truck-uuid-here",
    # "doordash:store_67890": "truck-uuid-here",
    # "telecom:sector_abc": "truck-uuid-here",
}

# Known truck names for fuzzy text matching against social captions.
# Populate from your actual Truck records (name -> id) once they exist in
# CloudKit. Names below match the real Sacramento/Plumas Lake-area trucks
# populated in scheduler.py's instagram_business_discovery_usernames — fill
# in the actual CloudKit truck IDs once you've created those Truck records
# (e.g. via DebugSeedDataView or CloudKit Dashboard).
KNOWN_TRUCK_NAMES: dict[str, str] = {
    # Deterministic IDs — computed from the same seed scheme the iOS app's
    # DebugSeedDataView.swift uses (deterministicTruckID(from:)). Tap
    # "Seed 14 Real Trucks Into CloudKit" in the app's Debug menu and it
    # will create these EXACT same IDs — nothing to copy or reconcile.
    # If the app ever shows a different ID than what's listed here for
    # the same truck, that means the two algorithms drifted — trust
    # whatever the app actually displays, since CloudKit's real records
    # are the source of truth, not this file.
    "drewski's": "aef2a8fe-c81f-3d00-70e8-2865f82f66e5",
    "buckhorn bbq": "0c305c27-2c83-cadb-0242-f3cb8f9ba988",
    "sactomofo": "88f02777-c70f-27e0-904e-63d752126949",
    "krush burger": "963de2ba-a448-7bb8-8fa1-b9bb008b0be2",
    "potato patoto": "2d64f57b-c49b-0b57-d027-34faa896d56a",
    "alameda tacos": "384a2291-8029-e61a-789c-f56d6907b4b8",
    "mucho nachos": "42ae8c26-93a8-95f8-9e09-076535083d92",
    "the pop up truck": "b4bc3e6f-548f-969a-3359-d95d964c2eb7",
    "santacos": "6b95d05b-dd65-e006-1ac1-a84a3ee50d39",
    "tacoa": "e9a67371-ac8c-a13e-78fb-a80014f53ff9",
    "tacos gto": "fc56801c-665d-9506-c9e5-3b135510414d",
    "tacomiendo": "0a391681-443b-0716-3901-26439e6192cd",
    "sac tacos": "a9e82fe6-62e4-3d6e-c66a-350ee5a08687",
    "the lumpia truck": "59341ec1-17ca-4a30-a0dc-be2ea40d2280",
}

CORROBORATION_WINDOW_MINUTES = 20
CORROBORATION_DISTANCE_MILES = 0.3

# Confidence thresholds for auto-attach vs. review queue
AUTO_ATTACH_THRESHOLD = 0.75


@dataclass
class RawDetection:
    source: str  # "traffic_cam" | "telecom_signal" | "delivery_pickup" | "social"
    latitude: float
    longitude: float
    timestamp: datetime.datetime
    raw_confidence: float  # 0.0-1.0, source's own confidence in "something is here"
    source_id: Optional[str] = None       # e.g. "uber:merchant_12345", used for DIRECT_ID_MAPPINGS
    text_hint: Optional[str] = None       # e.g. social caption text, used for name matching
    note: Optional[str] = None


@dataclass
class FusionResult:
    matched_truck_id: Optional[str]
    final_confidence: float
    reason: str
    corroborating_sources: list[str] = field(default_factory=list)


def _rough_miles(lat1, lon1, lat2, lon2) -> float:
    lat_miles = (lat1 - lat2) * 69.0
    lon_miles = (lon1 - lon2) * 54.6
    return math.sqrt(lat_miles ** 2 + lon_miles ** 2)


def _try_direct_id_match(detection: RawDetection) -> Optional[str]:
    if detection.source_id and detection.source_id in DIRECT_ID_MAPPINGS:
        return DIRECT_ID_MAPPINGS[detection.source_id]
    return None


def _try_name_match(detection: RawDetection) -> Optional[str]:
    if not detection.text_hint:
        return None
    text_lower = detection.text_hint.lower()
    for name, truck_id in KNOWN_TRUCK_NAMES.items():
        if name in text_lower:
            return truck_id
    return None


def _find_corroborating_detections(
    detection: RawDetection, recent_detections: list[RawDetection]
) -> list[RawDetection]:
    """Finds other recent detections (different sources) near this one in
    space and time — used to boost confidence even without a name/ID match."""
    corroborating = []
    for other in recent_detections:
        if other is detection or other.source == detection.source:
            continue
        time_diff = abs((detection.timestamp - other.timestamp).total_seconds()) / 60
        if time_diff > CORROBORATION_WINDOW_MINUTES:
            continue
        distance = _rough_miles(detection.latitude, detection.longitude, other.latitude, other.longitude)
        if distance <= CORROBORATION_DISTANCE_MILES:
            corroborating.append(other)
    return corroborating


def fuse_detection(detection: RawDetection, recent_detections: list[RawDetection]) -> FusionResult:
    """
    Core fusion logic for a single detection, given the pool of other
    recent detections (across all sources) to check for corroboration.
    """
    corroborators = _find_corroborating_detections(detection, recent_detections)
    corroboration_boost = min(0.15 * len(corroborators), 0.4)

    # 1. Direct ID mapping — highest confidence, no ambiguity.
    truck_id = _try_direct_id_match(detection)
    if truck_id:
        return FusionResult(
            matched_truck_id=truck_id,
            final_confidence=min(1.0, 0.95 + corroboration_boost),
            reason=f"direct_id_match:{detection.source_id}",
            corroborating_sources=[c.source for c in corroborators],
        )

    # 2. Name/text match (social captions mentioning a known truck).
    truck_id = _try_name_match(detection)
    if truck_id:
        confidence = min(1.0, 0.7 + corroboration_boost)
        return FusionResult(
            matched_truck_id=truck_id if confidence >= AUTO_ATTACH_THRESHOLD else None,
            final_confidence=confidence,
            reason="name_match" + (" (auto-attached)" if confidence >= AUTO_ATTACH_THRESHOLD else " (below threshold, needs review)"),
            corroborating_sources=[c.source for c in corroborators],
        )

    # 3. No direct match — corroboration alone can still be informative,
    # but never enough on its own to auto-attach to a SPECIFIC truck we
    # haven't identified. This always goes to the review queue.
    confidence = min(1.0, detection.raw_confidence + corroboration_boost)
    return FusionResult(
        matched_truck_id=None,
        final_confidence=confidence,
        reason=f"no_truck_match ({len(corroborators)} corroborating source(s))",
        corroborating_sources=[c.source for c in corroborators],
    )


def process_detection(detection: RawDetection, recent_detections: list[RawDetection]) -> None:
    """
    Runs fusion on a detection and writes the appropriate CloudKit record:
    a real Sighting if confidently matched, or an UnmatchedDetection for a
    human to resolve otherwise.
    """
    result = fuse_detection(detection, recent_detections)

    if result.matched_truck_id and result.final_confidence >= AUTO_ATTACH_THRESHOLD:
        confidence_level = "confirmed" if result.final_confidence >= 0.9 else "likely"
        sighting = {
            "id": str(uuid.uuid4()),
            "truckId": result.matched_truck_id,
            "latitude": detection.latitude,
            "longitude": detection.longitude,
            "note": detection.note or f"Auto-detected via {detection.source} ({result.reason})",
            "photoURL": "",
            "timestamp": detection.timestamp.isoformat(),
            "confidenceLevel": confidence_level,
            "expiresAt": (detection.timestamp + datetime.timedelta(hours=3)).isoformat(),
        }
        cloudkit_bridge.save_sighting(sighting)
        print(f"[fusion] auto-attached {detection.source} detection to truck {result.matched_truck_id} ({result.reason})")
    else:
        cloudkit_bridge.save_unmatched_detection({
            "id": str(uuid.uuid4()),
            "source": detection.source,
            "latitude": detection.latitude,
            "longitude": detection.longitude,
            "timestamp": detection.timestamp.isoformat(),
            "rawConfidence": result.final_confidence,
            "reason": result.reason,
            "textHint": detection.text_hint or "",
            "note": detection.note or "",
            "status": "pending",
        })
        print(f"[fusion] queued for human review: {detection.source} detection ({result.reason})")

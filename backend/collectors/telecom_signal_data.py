"""
Phase 3: cellular sector load anomaly detection.

This module assumes you have a direct data-sharing agreement with the
carrier(s) covering your testing area — per your note, that's in place for
your exclusive testing region. Cell-tower load/anomaly data isn't exposed
via any public API; it only exists because of that agreement, so this
code is scoped tightly to your test area and is NOT something to point at
other cities or carriers without their own separate agreement.

Every carrier's actual API shape will differ — this is a generic polling
pattern, not a working integration for any specific carrier. Swap the
field mapping in `_parse_anomaly` to match whatever your carrier's docs
actually specify once you have them in hand.

Concept: a tower sector serving an unusual load spike relative to its own
baseline (e.g. a normally quiet residential corner suddenly showing a
mid-day spike) is a proxy for "a crowd has gathered somewhere unusual" —
which a food truck causes as reliably as almost anything else. This is
inherently a probabilistic signal, not a confirmation — pair it with
crowdsourced or social confirmation before showing it to users as
anything above "possible activity detected."
"""

import os
import requests
from dataclasses import dataclass
from typing import Optional
import datetime

TELECOM_API_KEY = os.getenv("TELECOM_API_KEY", "")
TELECOM_API_BASE_URL = os.getenv("TELECOM_API_BASE_URL", "")

# Sector IDs covered by your testing agreement. Populate this with the
# actual sector/tower identifiers your carrier partner gave you — polling
# outside the sectors your agreement covers isn't something this should do.
AGREED_SECTOR_IDS: list[str] = []


@dataclass
class SectorAnomaly:
    sector_id: str
    latitude: float
    longitude: float
    baseline_load: float
    current_load: float
    anomaly_score: float  # e.g. (current - baseline) / baseline
    detected_at: datetime.datetime


def _parse_anomaly(row: dict) -> Optional[SectorAnomaly]:
    """
    ADJUST these field names to match your carrier partner's actual response
    schema — this is illustrative, not a confirmed working shape for any
    specific carrier's API.
    """
    try:
        baseline = float(row["baseline_load"])
        current = float(row["current_load"])
        return SectorAnomaly(
            sector_id=row["sector_id"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            baseline_load=baseline,
            current_load=current,
            anomaly_score=(current - baseline) / baseline if baseline else 0.0,
            detected_at=datetime.datetime.fromisoformat(row["timestamp"]),
        )
    except (KeyError, ValueError, ZeroDivisionError):
        return None


def fetch_sector_anomalies(min_anomaly_score: float = 0.5) -> list[SectorAnomaly]:
    """
    Polls your carrier partner's endpoint for current load on the sectors
    covered by your agreement, and returns those showing a load spike
    above `min_anomaly_score` relative to their own baseline.
    """
    if not TELECOM_API_KEY or not TELECOM_API_BASE_URL:
        raise RuntimeError(
            "TELECOM_API_KEY / TELECOM_API_BASE_URL not set. Fill these in "
            "with the credentials and endpoint your carrier partner provided."
        )
    if not AGREED_SECTOR_IDS:
        raise RuntimeError(
            "AGREED_SECTOR_IDS is empty — populate it with the sector/tower "
            "IDs your testing agreement actually covers before polling."
        )

    response = requests.get(
        f"{TELECOM_API_BASE_URL}/sectors/load",
        headers={"Authorization": f"Bearer {TELECOM_API_KEY}"},
        params={"sector_ids": ",".join(AGREED_SECTOR_IDS)},
        timeout=10,
    )
    response.raise_for_status()
    raw_rows = response.json().get("sectors", [])

    anomalies = []
    for row in raw_rows:
        parsed = _parse_anomaly(row)
        if parsed and parsed.anomaly_score >= min_anomaly_score:
            anomalies.append(parsed)
    return anomalies


def to_scheduled_post_candidates(anomalies: list[SectorAnomaly]) -> list[dict]:
    """
    Converts raw anomalies into the same shape used for `scheduled_posts`
    rows elsewhere in the pipeline (see schema.sql), tagged with
    source='telecom_signal' so the existing confidence-scoring logic can
    treat it consistently with other low-confidence, needs-confirmation
    sources.
    """
    return [
        {
            "source": "telecom_signal",
            "extracted_location": None,  # reverse-geocode lat/lng if you want a human-readable label
            "extracted_latitude": a.latitude,
            "extracted_longitude": a.longitude,
            "extracted_time": a.detected_at.isoformat(),
            "raw_source_url": None,
            "confidence_hint": "low",  # always pair with crowdsource/social confirmation
        }
        for a in anomalies
    ]


if __name__ == "__main__":
    print(
        "Set TELECOM_API_KEY, TELECOM_API_BASE_URL, and AGREED_SECTOR_IDS "
        "to your carrier partner's real values to test this module."
    )

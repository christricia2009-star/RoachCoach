from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from math import exp
from typing import Any

SOURCE_WEIGHT = {
    "owner": 1.0, "crowdsource": .82, "camera": .88, "social": .72,
    "event": .58, "municipal": .55, "delivery": .62, "schedule": .48,
    "web": .45, "telecom_signal": .25,
}


def _freshness(observed_at: datetime, now: datetime) -> float:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - observed_at).total_seconds() / 3600)
    return max(.05, exp(-age_hours / 12.0))


def fuse_evidence(observations: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in observations:
        truck_id = o.get("truckID") or o.get("truck_id")
        if truck_id:
            grouped[str(truck_id)].append(o)

    results = []
    for truck_id, items in grouped.items():
        contributions = []
        source_set = set()
        for o in items:
            raw = o.get("rawConfidence", o.get("raw_confidence", .5))
            try:
                raw = float(raw)
            except (TypeError, ValueError):
                raw = .5
            observed = o.get("observedAt") or o.get("observed_at")
            if isinstance(observed, str):
                try:
                    observed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                except ValueError:
                    observed = now
            if not isinstance(observed, datetime):
                observed = now
            source = str(o.get("source", "web"))
            weight = SOURCE_WEIGHT.get(source, .5)
            freshness = _freshness(observed, now)
            contribution = max(0.0, min(1.0, raw * weight * freshness))
            contributions.append(contribution)
            source_set.add(source)
        raw_sum = sum(sorted(contributions, reverse=True)[:8])
        confidence = max(0.0, min(.99, 1 - exp(-raw_sum * (1 + max(0, len(source_set)-1) * .18))))
        consensus = "Multi-source consensus" if len(source_set) >= 3 else "Two-source corroboration" if len(source_set) == 2 else "Single-source signal"
        results.append({"truckID": truck_id, "confidence": round(confidence, 4), "sourceCount": len(source_set), "consensus": consensus})
    return {"generatedAt": now.isoformat(), "results": sorted(results, key=lambda x: x["confidence"], reverse=True)}

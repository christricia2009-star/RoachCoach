# Roach Coach Radar — Phases 8, 9 & 10

## Phase 8 — AI Radar Brain
Explainable on-device prediction aggregation, predictive trails, evidence and movement anomaly scoring.

## Phase 9 — Intercept Mode
Converts a prediction into a target coordinate and estimated intercept time using the user's current location when available. Includes an Open in Maps action.

## Phase 10 — Anomaly + Self-Scoring
Flags predicted locations that materially diverge from recent activity centers and provides a local prediction hit/miss ledger so the prediction engine can be evaluated over time.

### Xcode
Add all Swift files under `iOS/RoachCoachRadar/Models`, `Views`, `Services`, and `Onboarding` to the existing target. RootTabView is already updated.

No additional CloudKit schema is required for these phases. Existing Truck and Sighting records are sufficient. CloudKit supports geographic locations and references on CKRecord; larger media can remain CKAsset-backed if enabled later.

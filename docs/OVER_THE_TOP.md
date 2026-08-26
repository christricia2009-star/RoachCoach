# Roach Coach Radar — Phase 4 Over-the-Top Pack

Implemented in source:

- On-device prediction engine: recency + weekday/hour pattern + spatial weighted center.
- Scout reputation / XP / badges stored locally.
- Geofenced 1/2-mile watch zones using Core Location.
- Local photo triage service using Vision; no photo upload is required.
- Radar Intelligence screen with prediction, reputation and heatmap summaries.
- Watch Zones screen.
- More tab entry points for the new features.

## CloudKit extension recommended

The existing deployed schema continues to work. For richer cross-device functionality, add these record types in development and deploy them after testing:

### RadarWatch
- userID: String
- truckID: String
- latitude: Location
- longitude: Location
- radiusMeters: Double
- enabled: Int(64)
- createdAt: Date

### SightingPhoto
- sightingID: String
- asset: Asset
- classifierScore: Double
- classifierLabels: [String]
- createdAt: Date

### Reputation
- userID: String
- xp: Int(64)
- confirmedReports: Int(64)
- totalReports: Int(64)
- accuracy: Double
- badges: [String]

### PredictionSnapshot
- truckID: String
- latitude: Double
- longitude: Double
- windowStart: Date
- windowEnd: Date
- confidence: Double
- generatedAt: Date
- evidence: [String]

CloudKit's public database supports query subscriptions; the existing Sighting subscription remains the real-time refresh mechanism. Assets are appropriate for photo/video files, and CLLocation is a supported CKRecord field type.

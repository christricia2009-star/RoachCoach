import Foundation
import CoreLocation

struct RadarObservation: Identifiable, Codable, Hashable, Sendable {
    enum SourceKind: String, Codable, CaseIterable, Sendable {
        // NOTE: the backend's live camera/telecom/delivery/municipal/
        // social sources (backend/main.py) and the scheduled pipeline
        // (backend/scheduler.py) both emit "telecom" for cellular
        // sector anomaly signals. That case was missing here, which
        // meant a SINGLE telecom observation in a scan response broke
        // Codable decoding for the ENTIRE observations array (Swift
        // enums with String raw values fail to decode on an unknown
        // case, and there's no `default` fallback) — the whole scan
        // would look empty even when the backend found real signals.
        case userReport, social, camera, event, municipal, delivery, schedule, owner, web, telecom
    }
    enum State: String, Codable, Sendable { case live, aging, stale, ghost, archived }

    let id: UUID
    let truckID: UUID?
    let source: SourceKind
    let sourceID: String
    let observedAt: Date
    let latitude: Double
    let longitude: Double
    let text: String?
    let sourceURL: String?
    let rawConfidence: Double
    var state: State
    var metadata: [String:String]

    var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    init(id: UUID = UUID(), truckID: UUID?=nil, source: SourceKind, sourceID: String, observedAt: Date = .now, latitude: Double, longitude: Double, text: String?=nil, sourceURL: String?=nil, rawConfidence: Double = 0.5, state: State = .live, metadata: [String:String]=[:]) {
        self.id = id; self.truckID = truckID; self.source = source; self.sourceID = sourceID; self.observedAt = observedAt; self.latitude = latitude; self.longitude = longitude; self.text = text; self.sourceURL = sourceURL; self.rawConfidence = rawConfidence; self.state = state; self.metadata = metadata
    }
}

struct EvidenceItem: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let observationID: UUID
    let label: String
    let source: RadarObservation.SourceKind
    let weight: Double
    let freshness: Double
    let independent: Bool
    let detail: String

    var contribution: Double { max(0, min(1, weight * freshness * (independent ? 1.0 : 0.65))) }
}

struct EvidenceFusionResult: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let truckID: UUID
    let confidence: Double
    let evidence: [EvidenceItem]
    let consensus: String
    let lastConfirmedAt: Date?
}

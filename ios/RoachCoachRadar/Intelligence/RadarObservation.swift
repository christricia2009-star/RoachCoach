import Foundation

struct RadarObservation: Identifiable, Codable, Hashable, Sendable {
    enum SourceKind: String, Codable, CaseIterable, Sendable {
        case userReport, social, camera, event, municipal, delivery, schedule, owner, web
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

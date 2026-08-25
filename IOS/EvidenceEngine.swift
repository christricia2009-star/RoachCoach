import Foundation

final class EvidenceEngine {
    static let shared = EvidenceEngine()
    private let sourceWeights: [RadarObservation.SourceKind: Double] = [
        .owner: 1.0, .userReport: 0.82, .camera: 0.88, .social: 0.72, .event: 0.58, .municipal: 0.55, .delivery: 0.62, .schedule: 0.48, .web: 0.45
    ]

    func fuse(truckID: UUID, observations: [RadarObservation], now: Date = .now) -> EvidenceFusionResult {
        let relevant = observations.filter { $0.truckID == truckID }
        let evidence = relevant.map { o -> EvidenceItem in
            let age = max(0, now.timeIntervalSince(o.observedAt) / 3600)
            let freshness = max(0.05, exp(-age / 12))
            return EvidenceItem(id:UUID(), observationID:o.id, label:o.source.rawValue.capitalized, source:o.source, weight:sourceWeights[o.source] ?? 0.5, freshness:freshness, independent:true, detail:o.text ?? "Observed by \(o.source.rawValue)")
        }.sorted { $0.contribution > $1.contribution }
        let top = evidence.prefix(8)
        let independentSources = Set(top.map(\.source)).count
        let raw = top.reduce(0.0) { $0 + $1.contribution }
        let confidence = max(0, min(0.99, 1 - exp(-raw * (1 + Double(independentSources-1) * 0.18))))
        let consensus = independentSources >= 3 ? "Multi-source consensus" : independentSources == 2 ? "Two-source corroboration" : "Single-source signal"
        return EvidenceFusionResult(id:UUID(), truckID:truckID, confidence:confidence, evidence:Array(top), consensus:consensus, lastConfirmedAt:relevant.map(\.observedAt).max())
    }
}

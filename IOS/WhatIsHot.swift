import Foundation

struct RadarBrief: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let title: String
    let detail: String
    let score: Int

    init(id: UUID = UUID(), title: String, detail: String, score: Int) {
        self.id = id
        self.title = title
        self.detail = detail
        self.score = score
    }
}

final class WhatIsHotEngine {
    static let shared = WhatIsHotEngine()

    private init() {}

    func brief(observations: [RadarObservation], now: Date = .now) -> RadarBrief {
        let recent = observations.filter { now.timeIntervalSince($0.observedAt) < 2 * 60 * 60 }
        let score = min(99, 50 + recent.count * 4)
        let sourceCount = Set(recent.map(\.source)).count
        let title = recent.isEmpty ? "RADAR QUIET" : "ACTIVITY IS HEATING UP"
        let detail = "\(recent.count) recent signals detected across \(sourceCount) source types."
        return RadarBrief(title: title, detail: detail, score: score)
    }
}

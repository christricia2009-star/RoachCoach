import Foundation
import CoreLocation

/// Canonical hotspot model. Keep this definition in one place to avoid Xcode
/// ambiguous-type/redeclaration errors.
struct RadarHotspot: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let latitude: Double
    let longitude: Double
    let score: Int
    let activeCount: Int
    let title: String

    var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    var intensity: Double {
        Double(max(0, min(100, score))) / 100.0
    }

    var count: Int { activeCount }
}

final class HotspotEngine {
    static let shared = HotspotEngine()

    func hotspots(observations: [RadarObservation]) -> [RadarHotspot] {
        let active = observations.filter {
            switch $0.state {
            case .live, .aging: return true
            case .stale, .ghost, .archived: return false
            }
        }

        let buckets = Dictionary(grouping: active) {
            "\(Int($0.latitude * 100))/\(Int($0.longitude * 100))"
        }

        return buckets.map { _, items in
            let lat = items.map(\.latitude).reduce(0, +) / Double(items.count)
            let lon = items.map(\.longitude).reduce(0, +) / Double(items.count)
            let sourceDiversity = Set(items.map(\.source)).count
            let score = min(99, 35 + items.count * 7 + sourceDiversity * 6)
            return RadarHotspot(
                id: UUID(),
                latitude: lat,
                longitude: lon,
                score: score,
                activeCount: items.count,
                title: "Radar hotspot"
            )
        }
        .sorted { $0.score > $1.score }
        .prefix(12)
        .map { $0 }
    }
}

import Foundation
import CoreLocation

final class AnomalyRadarService {
    static let shared = AnomalyRadarService()

    func detect(trucks: [Truck], sightings: [Sighting], now: Date = .now) -> [RadarAnomaly] {
        RadarBrain.shared.analyze(trucks: trucks, sightings: sightings, now: now).compactMap(\.anomaly)
            .sorted { $0.score > $1.score }
    }
}

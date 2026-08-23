import Foundation
import CoreLocation

struct RadarStats {
    let activeSightings: Int
    let confirmedSightings: Int
    let hotspots: Int
    let confidence: Int
    let nearestDistanceMiles: Double?
}

final class RadarEngine {
    static let shared = RadarEngine()

    func stats(sightings: [Sighting], location: CLLocation?) -> RadarStats {
        let active = sightings.filter { !$0.isExpired }
        let confirmed = active.filter { $0.confidenceLevel == .confirmed }.count
        let confidence = active.isEmpty ? 0 : Int((Double(active.reduce(0) { $0 + $1.confidenceLevel.sortWeight }) / Double(active.count) / 3.0 * 100).rounded())
        let distances = active.compactMap { sighting -> Double? in
            guard let location else { return nil }
            return location.distance(from: CLLocation(latitude: sighting.latitude, longitude: sighting.longitude)) / 1609.34
        }
        return RadarStats(
            activeSightings: active.count,
            confirmedSightings: confirmed,
            hotspots: buildHotspots(from: active).count,
            confidence: confidence,
            nearestDistanceMiles: distances.min()
        )
    }

    /// Legacy convenience used by the intelligence view. The canonical RadarHotspot
    /// type lives in Intelligence/HotspotEngine.swift so there is exactly one definition.
    func buildHotspots(from sightings: [Sighting]) -> [RadarHotspot] {
        var buckets: [String: (lat: Double, lng: Double, count: Int, weight: Double)] = [:]
        for sighting in sightings where !sighting.isExpired {
            let latBucket = (sighting.latitude * 100).rounded() / 100
            let lngBucket = (sighting.longitude * 100).rounded() / 100
            let key = "\(latBucket),\(lngBucket)"
            let current = buckets[key] ?? (latBucket, lngBucket, 0, 0)
            buckets[key] = (current.lat, current.lng, current.count + 1, current.weight + Double(sighting.confidenceLevel.sortWeight))
        }
        let maxWeight = buckets.values.map(\.weight).max() ?? 1
        return buckets.values.map { bucket in
            let score = Int((min(1, bucket.weight / maxWeight) * 100).rounded())
            return RadarHotspot(
                id: UUID(),
                latitude: bucket.lat,
                longitude: bucket.lng,
                score: score,
                activeCount: bucket.count,
                title: "Radar hotspot"
            )
        }.sorted { $0.score > $1.score }
    }
}

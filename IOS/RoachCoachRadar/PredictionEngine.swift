import Foundation
import CoreLocation

struct TruckPrediction: Identifiable, Hashable {
    let id: UUID
    let truckID: UUID
    let predictedCoordinate: CLLocationCoordinate2D
    let windowStart: Date
    let windowEnd: Date
    let confidence: Int
    let evidence: [String]
    let sampleCount: Int

    static func == (lhs: TruckPrediction, rhs: TruckPrediction) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// Lightweight on-device prediction engine. It learns from the sightings already
/// downloaded to the device: recency, weekday/hour, and spatial clustering.
final class PredictionEngine {
    static let shared = PredictionEngine()

    func predictions(for truck: Truck, sightings: [Sighting], now: Date = .now) -> [TruckPrediction] {
        let history = sightings.filter { $0.truckId == truck.id }
        guard !history.isEmpty else { return [] }

        let calendar = Calendar.current
        let weekday = calendar.component(.weekday, from: now)
        let hour = calendar.component(.hour, from: now)
        let candidates = history.sorted { $0.timestamp > $1.timestamp }

        let matching = candidates.filter {
            let d = calendar.dateComponents([.weekday, .hour], from: $0.timestamp)
            return d.weekday == weekday && abs((d.hour ?? 0) - hour) <= 3
        }
        let samples = matching.isEmpty ? Array(candidates.prefix(12)) : Array(matching.prefix(12))
        guard let center = weightedCenter(samples, now: now) else { return [] }

        let recencyScore = min(45, samples.reduce(0.0) { partial, sighting in
            let ageHours = max(0, now.timeIntervalSince(sighting.timestamp) / 3600)
            return partial + exp(-ageHours / 18.0) * 8.0
        })
        let patternScore = matching.isEmpty ? 15.0 : min(30.0, Double(matching.count) * 6.0)
        let confidence = min(99, max(35, Int((recencyScore + patternScore + 25).rounded())))

        let start = calendar.date(byAdding: .minute, value: 30, to: now) ?? now
        let end = calendar.date(byAdding: .hour, value: 3, to: start) ?? start
        var evidence = ["\(samples.count) recent radar samples"]
        if !matching.isEmpty { evidence.append("weekday/time pattern match") }
        if recencyScore > 25 { evidence.append("recent activity is strong") }

        return [TruckPrediction(id: UUID(), truckID: truck.id, predictedCoordinate: center,
                                windowStart: start, windowEnd: end, confidence: confidence,
                                evidence: evidence, sampleCount: samples.count)]
    }

    private func weightedCenter(_ sightings: [Sighting], now: Date) -> CLLocationCoordinate2D? {
        guard !sightings.isEmpty else { return nil }
        var lat = 0.0, lon = 0.0, total = 0.0
        for s in sightings {
            let age = max(0, now.timeIntervalSince(s.timestamp) / 3600)
            let weight = exp(-age / 24.0) * Double(s.confidenceLevel.sortWeight)
            lat += s.latitude * weight
            lon += s.longitude * weight
            total += weight
        }
        guard total > 0 else { return nil }
        return CLLocationCoordinate2D(latitude: lat / total, longitude: lon / total)
    }
}

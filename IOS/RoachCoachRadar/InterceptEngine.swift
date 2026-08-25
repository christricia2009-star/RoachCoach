import Foundation
import Combine
import CoreLocation

struct InterceptPlan: Identifiable, Hashable {
    let id: UUID
    let truck: Truck
    let coordinate: CLLocationCoordinate2D
    let eta: Date
    let confidence: Int
    let distanceMiles: Double?
    let reason: String

    init(id: UUID = UUID(), truck: Truck, coordinate: CLLocationCoordinate2D, eta: Date, confidence: Int, distanceMiles: Double?, reason: String) {
        self.id = id
        self.truck = truck
        self.coordinate = coordinate
        self.eta = eta
        self.confidence = confidence
        self.distanceMiles = distanceMiles
        self.reason = reason
    }

    static func == (lhs: InterceptPlan, rhs: InterceptPlan) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

final class InterceptEngine {
    static let shared = InterceptEngine()

    func plan(for truck: Truck, sightings: [Sighting], userLocation: CLLocation?, now: Date = .now) -> InterceptPlan? {
        guard let prediction = PredictionEngine.shared.predictions(for: truck, sightings: sightings, now: now).first else { return nil }
        let target = CLLocation(latitude: prediction.predictedCoordinate.latitude, longitude: prediction.predictedCoordinate.longitude)
        let distance = userLocation.map { target.distance(from: $0) / 1609.34 }
        let travelMinutes = distance.map { min(180, max(5, Int($0 * 4.0))) } ?? 0
        let eta = prediction.windowStart.addingTimeInterval(Double(travelMinutes) * 60)
        let confidence = max(25, prediction.confidence - (distance.map { Int(min(20, $0 * 2)) } ?? 0))
        let reason = distance.map { String(format: "Best predicted intercept is %.1f mi away; arrive near the start of the predicted window.", $0) } ?? "Enable location to calculate the fastest intercept from your position."
        return InterceptPlan(truck: truck, coordinate: prediction.predictedCoordinate, eta: eta, confidence: confidence, distanceMiles: distance, reason: reason)
    }
}

final class PredictionAccuracyStore: ObservableObject {
    static let shared = PredictionAccuracyStore()
    @Published private(set) var predictions = 0
    @Published private(set) var hits = 0
    private let key = "radar.prediction.accuracy.v1"
    private var loaded = false

    private init() { load() }
    var accuracy: Int { predictions == 0 ? 0 : Int((Double(hits) / Double(predictions) * 100).rounded()) }
    func record(hit: Bool) { predictions += 1; if hit { hits += 1 }; save() }
    private func load() {
        guard !loaded else { return }; loaded = true
        let d = UserDefaults.standard.dictionary(forKey: key) as? [String:Int] ?? [:]
        predictions = d["predictions"] ?? 0; hits = d["hits"] ?? 0
    }
    private func save() { UserDefaults.standard.set(["predictions": predictions, "hits": hits], forKey: key) }
}

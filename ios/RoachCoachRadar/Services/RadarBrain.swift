import Foundation
import CoreLocation

struct RadarAnomaly: Identifiable, Hashable {
    let id: UUID
    let truck: Truck
    let score: Int
    let message: String
    let coordinate: CLLocationCoordinate2D

    init(id: UUID = UUID(), truck: Truck, score: Int, message: String, coordinate: CLLocationCoordinate2D) {
        self.id = id
        self.truck = truck
        self.score = score
        self.message = message
        self.coordinate = coordinate
    }

    static func == (lhs: RadarAnomaly, rhs: RadarAnomaly) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct BrainPrediction: Identifiable, Hashable {
    let id: UUID
    let truck: Truck
    let prediction: TruckPrediction
    let route: [CLLocationCoordinate2D]
    let anomaly: RadarAnomaly?

    init(id: UUID = UUID(), truck: Truck, prediction: TruckPrediction, route: [CLLocationCoordinate2D], anomaly: RadarAnomaly?) {
        self.id = id
        self.truck = truck
        self.prediction = prediction
        self.route = route
        self.anomaly = anomaly
    }

    static func == (lhs: BrainPrediction, rhs: BrainPrediction) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

final class RadarBrain {
    static let shared = RadarBrain()

    func analyze(trucks: [Truck], sightings: [Sighting], now: Date = .now) -> [BrainPrediction] {
        trucks.compactMap { truck in
            guard let prediction = PredictionEngine.shared.predictions(for: truck, sightings: sightings, now: now).first else { return nil }
            let history = sightings.filter { $0.truckId == truck.id }.sorted { $0.timestamp > $1.timestamp }
            let points = Array(history.prefix(3)).map(\.coordinate)
            let route = Array(points.reversed()) + [prediction.predictedCoordinate]
            let anomaly = anomaly(for: truck, history: history, prediction: prediction)
            return BrainPrediction(truck: truck, prediction: prediction, route: route, anomaly: anomaly)
        }.sorted { $0.prediction.confidence > $1.prediction.confidence }
    }

    private func anomaly(for truck: Truck, history: [Sighting], prediction: TruckPrediction) -> RadarAnomaly? {
        guard history.count >= 3, let last = history.first else { return nil }
        let recent = Array(history.prefix(3))
        let center = CLLocation(latitude: recent.map(\.latitude).reduce(0,+) / Double(recent.count), longitude: recent.map(\.longitude).reduce(0,+) / Double(recent.count))
        let predicted = CLLocation(latitude: prediction.predictedCoordinate.latitude, longitude: prediction.predictedCoordinate.longitude)
        let drift = center.distance(from: predicted) / 1609.34
        guard drift > 3.0 else { return nil }
        let score = min(99, max(55, Int(drift * 10)))
        let message = String(format: "Predicted contact is %.1f mi outside its recent activity center.", drift)
        return RadarAnomaly(truck: truck, score: score, message: message, coordinate: last.coordinate)
    }
}

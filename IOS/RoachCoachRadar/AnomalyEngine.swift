import Foundation
import CoreLocation

struct RadarAnomalyFinding: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let truckID: UUID
    let severity: Int
    let title: String
    let detail: String
    let coordinate: RadarCoordinate?
}

final class AnomalyEngine {
    static let shared = AnomalyEngine()
    func analyze(truckID:UUID, observations:[RadarObservation], prediction:RadarPrediction?) -> [RadarAnomalyFinding] {
        let obs = observations.filter{$0.truckID==truckID}.sorted{$0.observedAt>$1.observedAt}
        guard let p = prediction, !obs.isEmpty else{return[]}
        let center = CLLocation(latitude:obs.prefix(6).map(\.latitude).reduce(0,+)/Double(min(obs.count,6)), longitude:obs.prefix(6).map(\.longitude).reduce(0,+)/Double(min(obs.count,6)))
        let distance = center.distance(from:p.coordinate.location)/1609.344
        guard distance > 3 else{return[]}
        return [RadarAnomalyFinding(id:UUID(),truckID:truckID,severity:min(99,max(55,Int(distance*11))),title:"Route anomaly",detail:String(format:"Prediction is %.1f mi outside recent activity center.",distance),coordinate:RadarCoordinate(center.coordinate))]
    }
}

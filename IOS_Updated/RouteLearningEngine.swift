import Foundation
import CoreLocation

struct RouteProfile: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let truckID: UUID
    let weekday: Int
    let hour: Int
    let center: RadarCoordinate
    let radiusMiles: Double
    let sampleCount: Int
    let reliability: Double
}

final class RouteLearningEngine {
    static let shared = RouteLearningEngine()
    func profiles(for truckID: UUID, observations:[RadarObservation], calendar:Calendar = .current) -> [RouteProfile] {
        let grouped = Dictionary(grouping: observations.filter{$0.truckID == truckID}) {
            let c = calendar.dateComponents([.weekday,.hour], from:$0.observedAt); return "\(c.weekday ?? 0)-\(c.hour ?? 0)"
        }
        return grouped.compactMap { key, items in
            guard items.count >= 2 else { return nil }
            let p = key.split(separator:"-").compactMap{Int($0)}; guard p.count==2 else{return nil}
            let lat = items.map(\.latitude).reduce(0,+)/Double(items.count), lon = items.map(\.longitude).reduce(0,+)/Double(items.count)
            let center = CLLocation(latitude:lat,longitude:lon)
            let radius = items.map{center.distance(from:CLLocation(latitude:$0.latitude,longitude:$0.longitude))/1609.344}.max() ?? 0.5
            return RouteProfile(id:UUID(),truckID:truckID,weekday:p[0],hour:p[1],center:RadarCoordinate(latitude:lat,longitude:lon),radiusMiles:max(0.25,radius),sampleCount:items.count,reliability:min(0.99,0.35+Double(items.count)*0.07))
        }.sorted{$0.reliability>$1.reliability}
    }
}

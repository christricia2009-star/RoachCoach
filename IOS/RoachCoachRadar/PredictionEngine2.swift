import Foundation

struct RadarPrediction: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let truckID: UUID
    let coordinate: RadarCoordinate
    let windowStart: Date
    let windowEnd: Date
    let confidence: Double
    let evidence: [String]
    let modelVersion: String
}

final class AdvancedPredictionEngine {
    static let shared = AdvancedPredictionEngine()
    func predict(truckID:UUID, observations:[RadarObservation], now:Date = .now) -> RadarPrediction? {
        let profiles = RouteLearningEngine.shared.profiles(for:truckID,observations:observations)
        let cal = Calendar.current; let wd = cal.component(.weekday,from:now); let hr = cal.component(.hour,from:now)
        let profile = profiles.first(where:{$0.weekday==wd && abs($0.hour-hr)<=2}) ?? profiles.first
        let relevant = observations.filter{$0.truckID==truckID}.sorted{$0.observedAt>$1.observedAt}
        guard let last = relevant.first ?? nil else { return nil }
        let coord = profile?.center ?? RadarCoordinate(latitude:last.latitude,longitude:last.longitude)
        let pattern = profile?.reliability ?? 0.35
        let recency = max(0.05,exp(-max(0,now.timeIntervalSince(last.observedAt)/3600)/18))
        let sourceDiversity = Double(Set(relevant.prefix(8).map(\.source)).count)/5.0
        let confidence = min(0.98,0.35+pattern*0.35+recency*0.2+min(0.15,sourceDiversity*0.15))
        let start = cal.date(byAdding:.minute,value:15,to:now) ?? now
        let end = cal.date(byAdding:.minute,value:90,to:start) ?? start
        var evidence = ["\(relevant.count) observations","last signal \(last.observedAt.formatted(date:.omitted,time:.shortened))"]
        if profile != nil { evidence.append("historical route/time pattern") }
        return RadarPrediction(id:UUID(),truckID:truckID,coordinate:coord,windowStart:start,windowEnd:end,confidence:confidence,evidence:evidence,modelVersion:"RCR-27.515")
    }
}

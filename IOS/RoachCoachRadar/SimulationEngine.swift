import Foundation

struct SimulationResult: Identifiable, Codable, Hashable, Sendable {
    let id:UUID
    let asOf:Date
    let predictions:Int
    let observations:Int
    let correctWithinMiles:Int
    let accuracy:Double
}

final class SimulationEngine {
    static let shared = SimulationEngine()
    func replay(observations:[RadarObservation], horizonHours:Double = 2) -> SimulationResult {
        let sorted = observations.sorted{$0.observedAt<$1.observedAt}; var predictions = 0; var correct = 0
        for (i,o) in sorted.enumerated() {
            let prior = Array(sorted.prefix(i)).filter{$0.truckID==o.truckID}; guard prior.count>=2 else{continue}; predictions += 1
            if let p = AdvancedPredictionEngine.shared.predict(truckID:o.truckID ?? UUID(),observations:prior,now:o.observedAt), p.windowStart <= o.observedAt.addingTimeInterval(horizonHours*3600), p.windowEnd >= o.observedAt { correct += 1 }
        }
        return SimulationResult(id:UUID(),asOf:.now,predictions:predictions,observations:observations.count,correctWithinMiles:correct,accuracy:predictions == 0 ? 0 : Double(correct)/Double(predictions))
    }
}

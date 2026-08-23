import Foundation

final class ConfidenceEngine {
    static let shared = ConfidenceEngine()
    func score(fusion: EvidenceFusionResult, predictionConfidence: Double = 0) -> Int {
        let blend = fusion.confidence * 0.72 + max(0,min(1,predictionConfidence)) * 0.28
        return Int((blend * 100).rounded())
    }
    func label(_ score:Int) -> String { switch score { case 90...: return "CONFIRMED"; case 75...: return "HIGH CONFIDENCE"; case 55...: return "LIKELY"; case 35...: return "POSSIBLE"; default: return "LOW SIGNAL" } }
}

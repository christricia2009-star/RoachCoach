import Foundation

struct AIUsageSnapshot: Codable, Hashable, Sendable {
    var calls:Int = 0; var estimatedCost:Double = 0; var cacheHits:Int = 0
    var cacheHitRate:Double { calls == 0 ? 0 : Double(cacheHits)/Double(calls) }
}

final class CostOptimizer {
    static let shared = CostOptimizer()
    private var cache = [String:(Date,String)]()
    private(set) var usage = AIUsageSnapshot()
    func shouldEscalate(signal:Double) -> Bool { signal >= 0.62 }
    func cached(prompt:String, maxAge:TimeInterval = 900) -> String? {
        guard let item = cache[prompt], Date().timeIntervalSince(item.0)<maxAge else{return nil}
        usage.cacheHits += 1; return item.1
    }
    func store(prompt:String,response:String,estimatedCost:Double) { cache[prompt]=(Date(),response); usage.calls += 1; usage.estimatedCost += estimatedCost }
}

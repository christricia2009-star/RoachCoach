import Foundation

protocol RadarSource: Sendable {
    var id:String { get }
    var displayName:String { get }
    func collect(latitude:Double,longitude:Double,radiusMiles:Double) async throws -> [RadarObservation]
}

struct SourceStatus: Identifiable, Codable, Hashable, Sendable {
    let id:String; let name:String; let status:String; let detail:String; let durationMS:Int
}

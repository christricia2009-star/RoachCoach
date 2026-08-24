import Foundation
import Combine

struct RadarScanPacket: Identifiable, Codable, Sendable {
    let id:UUID; let scannedAt:Date; let observations:[RadarObservation]; let sources:[SourceStatus]; let hotspots:[RadarHotspot]; let brief:RadarBrief
}

@MainActor final class RadarOrchestrator: ObservableObject {
    static let shared = RadarOrchestrator()
    @Published private(set) var packet:RadarScanPacket?
    @Published private(set) var isScanning = false

    func scan(latitude:Double,longitude:Double,radiusMiles:Double,backendURL:String) async {
        isScanning = true; defer{isScanning = false}
        var all:[RadarObservation]=[]; var statuses:[SourceStatus]=[]
        let start = Date()
        if let url = URL(string:backendURL.trimmingCharacters(in:.whitespacesAndNewlines).hasSuffix("/") ? backendURL : backendURL+"/") {
            let source = BackendRadarSource(baseURL:url); let s = Date(); do { let o = try await source.collect(latitude:latitude,longitude:longitude,radiusMiles:radiusMiles); all += o; statuses.append(SourceStatus(id:source.id,name:source.displayName,status:"ok",detail:"\(o.count) observations",durationMS:Int(Date().timeIntervalSince(s)*1000))) } catch { statuses.append(SourceStatus(id:source.id,name:source.displayName,status:"error",detail:error.localizedDescription,durationMS:Int(Date().timeIntervalSince(s)*1000))) }
            let camera = CameraRadarSource(endpoint:url.appendingPathComponent("cameras/near").absoluteString); _ = camera
        }
        let hotspots = HotspotEngine.shared.hotspots(observations:all); let brief = WhatIsHotEngine.shared.brief(observations:all)
        packet = RadarScanPacket(id:UUID(),scannedAt:Date(),observations:all,sources:statuses,hotspots:hotspots,brief:brief)
        _ = start
    }
}

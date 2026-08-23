import Foundation

struct BackendRadarSource: RadarSource {
    let id="backend"; let displayName="Radar backend"; let baseURL:URL
    func collect(latitude:Double,longitude:Double,radiusMiles:Double) async throws -> [RadarObservation] {
        var req = URLRequest(url:baseURL.appendingPathComponent("radar/observations")); req.httpMethod="POST"; req.setValue("application/json",forHTTPHeaderField:"Content-Type"); req.httpBody = try JSONEncoder().encode(["latitude":latitude,"longitude":longitude,"radiusMiles":radiusMiles])
        let (data,response)=try await URLSession.shared.data(for:req); guard let h = response as? HTTPURLResponse,(200..<300).contains(h.statusCode) else{throw URLError(.badServerResponse)}
        return try JSONDecoder().decode([RadarObservation].self,from:data)
    }
}

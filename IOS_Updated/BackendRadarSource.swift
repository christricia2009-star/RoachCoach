import Foundation

/// Radar source for the deployed Vercel/FastAPI radar endpoint.
/// The backend accepts POST /radar/observations. This implementation also
/// reports the actual HTTP status/body so a future deployment mismatch is
/// immediately visible instead of becoming a generic 405/500.
struct BackendRadarSource: RadarSource {
    let id = "backend"
    let displayName = "Radar backend"
    let baseURL: URL

    private struct RequestBody: Encodable {
        let latitude: Double
        let longitude: Double
        let radiusMiles: Double
    }

    func collect(latitude: Double, longitude: Double, radiusMiles: Double) async throws -> [RadarObservation] {
        // Accept a base URL with or without a trailing slash and with an
        // accidental /api suffix. The FastAPI compatibility route is mounted
        // at /radar/observations, not /api/radar/observations.
        var root = baseURL
        if root.path.hasSuffix("/api") {
            root.deleteLastPathComponent()
        }
        let url = root.appendingPathComponent("radar/observations")

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(
            RequestBody(latitude: latitude, longitude: longitude, radiusMiles: radiusMiles)
        )

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }

        guard (200..<300).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? "<non-UTF8 response>"
            print("Radar backend HTTP \(http.statusCode) \(url): \(body)")
            throw NSError(
                domain: "BackendRadarSource",
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "Radar backend returned HTTP \(http.statusCode): \(body)"]
            )
        }

        return try JSONDecoder().decode([RadarObservation].self, from: data)
    }
}

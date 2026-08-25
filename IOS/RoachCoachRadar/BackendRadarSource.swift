import Foundation

/// Radar source backed by the deployed FastAPI/Vercel radar endpoint.
///
/// IMPORTANT:
/// The production backend exposes:
///
///     POST /api/radar/scan
///
/// Do NOT use /radar/observations here.
/// That endpoint was responsible for the HTTP 405
/// "Method Not Allowed" error.
struct BackendRadarSource: RadarSource {
    let id = "backend"
    let displayName = "Radar backend"
    let baseURL: URL

    private struct RequestBody: Encodable {
        let latitude: Double
        let longitude: Double
        let radiusMiles: Double
    }

    func collect(
        latitude: Double,
        longitude: Double,
        radiusMiles: Double
    ) async throws -> [RadarObservation] {

        let url = makeRadarScanURL()

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 60

        request.httpBody = try JSONEncoder().encode(
            RequestBody(
                latitude: latitude,
                longitude: longitude,
                radiusMiles: radiusMiles
            )
        )

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }

        let body = String(data: data, encoding: .utf8) ?? ""

        guard (200..<300).contains(http.statusCode) else {
            print("========================================")
            print("RADAR BACKEND ERROR")
            print("URL: \(url.absoluteString)")
            print("HTTP: \(http.statusCode)")
            print("BODY: \(body)")
            print("========================================")

            throw NSError(
                domain: "BackendRadarSource",
                code: http.statusCode,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "Radar backend returned HTTP \(http.statusCode): \(body)"
                ]
            )
        }

        // The backend radar scan may return either:
        //
        // 1. A direct array of RadarObservation
        // 2. A scan envelope containing observations
        //
        // Try the direct format first.
        if let observations = try? JSONDecoder.apiDecoder.decode(
            [RadarObservation].self,
            from: data
        ) {
            return observations
        }

        // Compatibility envelope.
        struct RadarEnvelope: Decodable {
            let observations: [RadarObservation]?
        }

        if let envelope = try? JSONDecoder.apiDecoder.decode(
            RadarEnvelope.self,
            from: data
        ) {
            return envelope.observations ?? []
        }

        // Give a useful decoding error rather than silently returning [].
        throw NSError(
            domain: "BackendRadarSource",
            code: -2,
            userInfo: [
                NSLocalizedDescriptionKey:
                    "Radar backend returned HTTP 200, but the response could not be decoded as radar observations. Response: \(body)"
            ]
        )
    }

    private func makeRadarScanURL() -> URL {
        var root = baseURL

        // Remove a trailing /api because we explicitly add it below.
        //
        // This makes both of these settings work:
        //
        // https://radar.snapcollectibles.com
        // https://radar.snapcollectibles.com/api
        //
        // without accidentally producing:
        //
        // /api/api/radar/scan
        if root.path == "/api" || root.path.hasSuffix("/api/") {
            root.deleteLastPathComponent()
        }

        return root.appendingPathComponent("api/radar/scan")
    }
}

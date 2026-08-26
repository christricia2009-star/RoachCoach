import Foundation
import Combine
import CoreLocation

struct RadarScanRequest: Codable, Sendable {
    let latitude: Double
    let longitude: Double
    let radiusMiles: Double
}

struct RadarScanResult: Codable, Sendable, Identifiable {
    let id: UUID
    let scannedAt: Date
    let sources: [RadarSourceResult]
    let cameras: [RadarCameraResult]
    let sightings: [Sighting]
    let observations: [RadarObservation]
    let summary: String
    let confidence: Double
    let engineVersion: String?
    let evidenceCount: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case scannedAt = "scanned_at"
        case sources
        case cameras
        case sightings
        case observations
        case summary
        case confidence
        case engineVersion = "engine_version"
        case evidenceCount = "evidence_count"
    }
}

struct RadarSourceResult: Codable, Sendable, Identifiable {
    let id: String
    let name: String
    let status: String
    let detail: String
}

struct RadarCameraResult: Codable, Sendable, Identifiable {
    let id: String
    let locationName: String
    let county: String?
    let route: String?
    let latitude: Double
    let longitude: Double
    let currentImageURL: String?
    let inService: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case locationName = "location_name"
        case county
        case route
        case latitude
        case longitude
        case currentImageURL = "current_image_url"
        case inService = "in_service"
    }
}

@MainActor
final class RadarScanService: ObservableObject {

    static let shared = RadarScanService()

    @Published private(set) var isScanning = false
    @Published private(set) var lastResult: RadarScanResult?
    @Published private(set) var lastError: String?

    private init() {}

    // MARK: - Radar Scan

    func scan(
        location: CLLocation,
        radiusMiles: Double = 10
    ) async -> RadarScanResult? {

        guard let url = endpoint(path: "api/radar/scan") else {
            lastError = "Enter your Radar Backend URL in Settings first."
            return nil
        }

        isScanning = true
        lastError = nil

        defer {
            isScanning = false
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(
            "application/json",
            forHTTPHeaderField: "Content-Type"
        )
        request.setValue(
            "application/json",
            forHTTPHeaderField: "Accept"
        )
        request.timeoutInterval = 60

        APIKeyStore.shared.headers().forEach {
            request.setValue($1, forHTTPHeaderField: $0)
        }

        request.httpBody = try? JSONEncoder.apiEncoder.encode(
            RadarScanRequest(
                latitude: location.coordinate.latitude,
                longitude: location.coordinate.longitude,
                radiusMiles: radiusMiles
            )
        )

        do {
            let (data, response) = try await URLSession.shared.data(
                for: request
            )

            guard let http = response as? HTTPURLResponse else {
                throw URLError(.badServerResponse)
            }

            let body = String(data: data, encoding: .utf8) ?? ""

            guard (200..<300).contains(http.statusCode) else {
                print("========================================")
                print("RADAR SCAN ERROR")
                print("URL: \(url.absoluteString)")
                print("HTTP: \(http.statusCode)")
                print("BODY: \(body)")
                print("========================================")

                throw NSError(
                    domain: "RadarScanService",
                    code: http.statusCode,
                    userInfo: [
                        NSLocalizedDescriptionKey:
                            "Radar scan returned HTTP \(http.statusCode): \(body)"
                    ]
                )
            }

            let result = try JSONDecoder.apiDecoder.decode(
                RadarScanResult.self,
                from: data
            )

            lastResult = result
            return result

        } catch {
            lastError = error.localizedDescription

            print("========================================")
            print("RADAR SCAN FAILED")
            print(error)
            print("========================================")

            return nil
        }
    }

    // MARK: - Health

    func healthCheck() async -> Bool {

        guard let url = endpoint(path: "api/health") else {
            return false
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 10

        APIKeyStore.shared.headers().forEach {
            request.setValue($1, forHTTPHeaderField: $0)
        }

        do {
            let (_, response) = try await URLSession.shared.data(
                for: request
            )

            return (response as? HTTPURLResponse)?.statusCode == 200

        } catch {
            print("Health check failed: \(error)")
            return false
        }
    }

    // MARK: - Endpoint

    private func endpoint(path: String) -> URL? {

        var value = APIKeyStore.shared.backendURL
            .trimmingCharacters(in: .whitespacesAndNewlines)

        guard !value.isEmpty else {
            return nil
        }

        if !value.hasPrefix("http://") &&
            !value.hasPrefix("https://") {

            value = "https://" + value
        }

        guard var base = URL(string: value) else {
            return nil
        }

        // Normalize a backend URL accidentally entered as:
        //
        // https://radar.snapcollectibles.com/api
        //
        // so callers can safely request:
        //
        // api/radar/scan
        //
        // without producing /api/api/radar/scan.
        if base.path == "/api" ||
            base.path.hasSuffix("/api/") {

            base.deleteLastPathComponent()
        }

        return base.appendingPathComponent(path)
    }
}

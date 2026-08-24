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
        case sources, cameras, sightings, observations
        case summary, confidence
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
        case county, route, latitude, longitude
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

    func scan(location: CLLocation, radiusMiles: Double = 10) async -> RadarScanResult? {
        // main.py namespaces every route under /api (see APIService.swift's
        // "api/trucks", "api/sightings" comments) — this was previously
        // "radar/scan" with no prefix, which 404'd against the real
        // backend and surfaced as NSURLErrorDomain -1011 (bad server response).
        guard let url = endpoint(path: "api/radar/scan") else {
            lastError = "Enter your Radar Backend URL in Settings first."
            return nil
        }
        isScanning = true
        lastError = nil
        defer { isScanning = false }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60
        APIKeyStore.shared.headers().forEach { request.setValue($1, forHTTPHeaderField: $0) }
        request.httpBody = try? JSONEncoder.apiEncoder.encode(
            RadarScanRequest(latitude: location.coordinate.latitude,
                             longitude: location.coordinate.longitude,
                             radiusMiles: radiusMiles)
        )

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw URLError(.badServerResponse)
            }
            let result = try JSONDecoder.apiDecoder.decode(RadarScanResult.self, from: data)
            lastResult = result
            return result
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    func healthCheck() async -> Bool {
        guard let url = endpoint(path: "api/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch { return false }
    }

    private func endpoint(path: String) -> URL? {
        var value = APIKeyStore.shared.backendURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        if !value.hasPrefix("http://") && !value.hasPrefix("https://") { value = "https://" + value }
        guard let base = URL(string: value) else { return nil }
        return base.appendingPathComponent(path)
    }
}

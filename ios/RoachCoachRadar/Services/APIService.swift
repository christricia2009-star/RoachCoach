import Foundation

/// Abstraction over data access. `MockAPIService` is wired up by default so the
/// app runs fully standalone. To connect the real backend (see /Backend),
/// implement `LiveAPIService` below with real URLSession calls to your
/// deployed FastAPI server and swap the `shared` instance in
/// FoodTruckTrackerApp.swift.
protocol APIServicing {
    func fetchTrucks() async throws -> [Truck]
    func fetchSightings() async throws -> [Sighting]
    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting]
    func submitSighting(_ sighting: Sighting) async throws
    func fetchUser() async throws -> AppUser
    func updateFavorites(_ truckIds: [UUID]) async throws
}

final class MockAPIService: APIServicing {
    static let shared = MockAPIService()
    private let mock = MockDataService.shared
    private var currentUser = AppUser(displayName: "Guest", homeCity: "San Francisco")

    func fetchTrucks() async throws -> [Truck] {
        mock.trucks
    }

    func fetchSightings() async throws -> [Sighting] {
        mock.sightings.filter { !$0.isExpired }
    }

    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting] {
        mock.sightings(for: truckId)
    }

    func submitSighting(_ sighting: Sighting) async throws {
        mock.addSighting(sighting)
    }

    func fetchUser() async throws -> AppUser {
        currentUser
    }

    func updateFavorites(_ truckIds: [UUID]) async throws {
        currentUser.favoriteTruckIds = truckIds
    }
}

/// STUB: fill this in once /Backend is deployed somewhere reachable
/// (e.g. https://api.yourfoodtruckapp.com). Every function mirrors the
/// FastAPI routes defined in Backend/main.py.
final class LiveAPIService: APIServicing {
    static let shared = LiveAPIService()
    private let baseURL = URL(string: "https://REPLACE_WITH_YOUR_DEPLOYED_BACKEND_URL")!

    func fetchTrucks() async throws -> [Truck] {
        let (data, _) = try await URLSession.shared.data(from: baseURL.appendingPathComponent("trucks"))
        return try JSONDecoder.apiDecoder.decode([Truck].self, from: data)
    }

    func fetchSightings() async throws -> [Sighting] {
        let (data, _) = try await URLSession.shared.data(from: baseURL.appendingPathComponent("sightings"))
        return try JSONDecoder.apiDecoder.decode([Sighting].self, from: data)
    }

    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting] {
        let url = baseURL.appendingPathComponent("trucks/\(truckId.uuidString)/sightings")
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONDecoder.apiDecoder.decode([Sighting].self, from: data)
    }

    func submitSighting(_ sighting: Sighting) async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent("sightings"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.apiEncoder.encode(sighting)
        _ = try await URLSession.shared.data(for: request)
    }

    func fetchUser() async throws -> AppUser {
        let (data, _) = try await URLSession.shared.data(from: baseURL.appendingPathComponent("users/me"))
        return try JSONDecoder.apiDecoder.decode(AppUser.self, from: data)
    }

    func updateFavorites(_ truckIds: [UUID]) async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent("users/me/favorites"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.apiEncoder.encode(truckIds)
        _ = try await URLSession.shared.data(for: request)
    }
}

extension JSONDecoder {
    static var apiDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

extension JSONEncoder {
    static var apiEncoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}

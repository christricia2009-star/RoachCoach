import Foundation
import CloudKit

protocol APIServicing {
    func fetchTrucks() async throws -> [Truck]
    func fetchSightings() async throws -> [Sighting]
    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting]
    func submitSighting(_ sighting: Sighting) async throws
    func fetchUser() async throws -> AppUser
    func updateFavorites(_ truckIds: [UUID]) async throws
    func testConnection() async -> Bool   // fixed casing (was testconnection)
}

final class MockAPIService: APIServicing {
    static let shared = MockAPIService()
    private let mock = MockDataService.shared
    private var currentUser = AppUser(displayName: "Guest", homeCity: "San Francisco")

    func testConnection() async -> Bool {
        true
    }

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

final class LiveAPIService: APIServicing {

    static let shared = LiveAPIService()

    private let baseURL = URL(string: "https://radar.snapcollectibles.com")!

    // CloudKit — same container/database the app already reads from via
    // CloudKitService.swift. fetchUser/updateFavorites go here, NOT to
    // radar.snapcollectibles.com — main.py has no /users routes; user
    // data lives in CloudKit only (see BackendUpdate/UPDATE_README.md).
    private let container = CKContainer.default()
    private lazy var privateDB = container.privateCloudDatabase

    private let userRecordType = "AppUser"
    private let favoriteTruckIdsField = "favoriteTruckIds"
    private let displayNameField = "displayName"
    private let homeCityField = "homeCity"

    // MARK: - Radar Health

    func testConnection() async -> Bool {
        do {
            var request = URLRequest(
                url: baseURL.appendingPathComponent("api/health")
            )

            request.httpMethod = "GET"
            request.timeoutInterval = 15

            let (data, response) = try await URLSession.shared.data(for: request)

            guard let httpResponse = response as? HTTPURLResponse else {
                return false
            }

            guard httpResponse.statusCode == 200 else {
                print("Radar health HTTP status: \(httpResponse.statusCode)")
                return false
            }

            print("Radar health response: \(String(data: data, encoding: .utf8) ?? "")")

            return true

        } catch {
            print("Radar connection failed: \(error)")
            return false
        }
    }

    // MARK: - Trucks

    func fetchTrucks() async throws -> [Truck] {
        // fixed: was missing "api/" prefix (was appendingPathComponent("trucks"))
        let url = baseURL.appendingPathComponent("api/trucks")

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(
            [Truck].self,
            from: data
        )
    }

    // MARK: - Sightings

    func fetchSightings() async throws -> [Sighting] {
        // fixed: was missing "api/" prefix
        let url = baseURL.appendingPathComponent("api/sightings")

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(
            [Sighting].self,
            from: data
        )
    }

    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting] {
        // fixed: was missing "api/" prefix, and route shape must match
        // main.py's GET /api/trucks/{truck_id}/sightings exactly.
        let url = baseURL
            .appendingPathComponent("api/trucks")
            .appendingPathComponent(truckId.uuidString)
            .appendingPathComponent("sightings")

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(
            [Sighting].self,
            from: data
        )
    }

    // MARK: - Submit Sighting

    func submitSighting(_ sighting: Sighting) async throws {
        // fixed: was missing "api/" prefix
        let url = baseURL.appendingPathComponent("api/sightings")

        var request = URLRequest(url: url)

        request.httpMethod = "POST"
        request.timeoutInterval = 20

        request.setValue(
            "application/json",
            forHTTPHeaderField: "Content-Type"
        )

        request.httpBody = try JSONEncoder.apiEncoder.encode(sighting)

        let (_, response) = try await URLSession.shared.data(
            for: request
        )

        try validate(response)
    }

    // MARK: - User (CloudKit, not the FastAPI backend)

    func fetchUser() async throws -> AppUser {
        let userRecordID = try await container.userRecordID()

        do {
            let record = try await privateDB.record(for: userRecordID)
            return try appUser(from: record)
        } catch let ckError as CKError where ckError.code == .unknownItem {
            // No AppUser record yet for this iCloud user — create a default
            // one so subsequent fetches/updates have something to work with.
            let newRecord = CKRecord(recordType: userRecordType, recordID: userRecordID)
            newRecord[displayNameField] = "Guest" as CKRecordValue
            newRecord[homeCityField] = "" as CKRecordValue
            newRecord[favoriteTruckIdsField] = [] as CKRecordValue

            let saved = try await privateDB.save(newRecord)
            return try appUser(from: saved)
        }
    }

    // MARK: - Favorites

    func updateFavorites(_ truckIds: [UUID]) async throws {
        let userRecordID = try await container.userRecordID()
        let record = try await privateDB.record(for: userRecordID)

        record[favoriteTruckIdsField] = truckIds.map { $0.uuidString } as CKRecordValue

        _ = try await privateDB.save(record)
    }

    // MARK: - CloudKit <-> AppUser mapping
    // NOTE: adjust field names above / AppUser initializer here if your
    // actual AppUser struct has more properties than displayName/homeCity/
    // favoriteTruckIds.

    private func appUser(from record: CKRecord) throws -> AppUser {
        let displayName = record[displayNameField] as? String ?? "Guest"
        let homeCity = record[homeCityField] as? String ?? ""
        let favoriteStrings = record[favoriteTruckIdsField] as? [String] ?? []
        let favoriteTruckIds = favoriteStrings.compactMap { UUID(uuidString: $0) }

        var user = AppUser(displayName: displayName, homeCity: homeCity)
        user.favoriteTruckIds = favoriteTruckIds
        return user
    }

    // MARK: - HTTP Validation

    private func validate(_ response: URLResponse) throws {

        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpError(http.statusCode)
        }
    }
}

enum APIError: LocalizedError {

    case invalidResponse
    case httpError(Int)

    var errorDescription: String? {

        switch self {

        case .invalidResponse:
            return "Invalid response from Radar backend."

        case .httpError(let status):
            return "Radar backend returned HTTP \(status)."
        }
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

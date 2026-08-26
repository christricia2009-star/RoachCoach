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

    // MARK: - Menu + Order Ahead
    func fetchMenu(forTruck truckId: UUID, availableOnly: Bool) async throws -> [MenuItem]
    func createOrder(_ request: NewOrderRequest) async throws -> Order
    func fetchOrder(id: String) async throws -> Order

    // MARK: - Owner Order Board
    func fetchOrders(forTruck truckId: UUID, activeOnly: Bool) async throws -> [Order]
    func updateOrderStatus(orderId: String, status: OrderStatus, pickupEtaMinutes: Int?) async throws -> Order

    // MARK: - Payments (Phase 5)
    func fetchPaymentsConfig() async throws -> PaymentsConfig
    func createStripePaymentIntent(orderId: String) async throws -> StripePaymentIntent
    func chargeSquare(orderId: String, sourceId: String, verificationToken: String?) async throws -> PaymentResult
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

    // MARK: - Menu + Order Ahead

    func fetchMenu(forTruck truckId: UUID, availableOnly: Bool) async throws -> [MenuItem] {
        let items = mock.menuItems(for: truckId)
        return availableOnly ? items.filter(\.isAvailable) : items
    }

    func createOrder(_ request: NewOrderRequest) async throws -> Order {
        mock.createOrder(from: request)
    }

    func fetchOrder(id: String) async throws -> Order {
        guard let order = mock.order(id: id) else {
            throw APIError.httpError(404)
        }
        return order
    }

    // MARK: - Owner Order Board

    func fetchOrders(forTruck truckId: UUID, activeOnly: Bool) async throws -> [Order] {
        let orders = mock.orders(for: truckId)
        guard activeOnly else { return orders }
        return orders.filter { $0.status != .completed && $0.status != .cancelled }
    }

    func updateOrderStatus(orderId: String, status: OrderStatus, pickupEtaMinutes: Int?) async throws -> Order {
        guard let updated = mock.updateOrderStatus(orderId: orderId, status: status, pickupEtaMinutes: pickupEtaMinutes) else {
            throw APIError.httpError(404)
        }
        return updated
    }

    // MARK: - Payments (Phase 5)

    func fetchPaymentsConfig() async throws -> PaymentsConfig {
        PaymentsConfig(
            provider: "stripe",
            stripe: .init(enabled: true, publishableKey: "pk_test_mock"),
            square: .init(enabled: false, applicationId: nil, locationId: nil, environment: "sandbox")
        )
    }

    func createStripePaymentIntent(orderId: String) async throws -> StripePaymentIntent {
        guard let order = mock.order(id: orderId) else { throw APIError.httpError(404) }
        return StripePaymentIntent(
            provider: "stripe",
            paymentIntentId: "pi_mock_\(orderId)",
            clientSecret: "pi_mock_\(orderId)_secret_mock",
            status: "requires_payment_method",
            amountCents: order.totalCents,
            currency: order.currency.lowercased()
        )
    }

    func chargeSquare(orderId: String, sourceId: String, verificationToken: String?) async throws -> PaymentResult {
        guard let updated = mock.markOrderPaid(orderId: orderId, provider: "square") else {
            throw APIError.httpError(404)
        }
        return PaymentResult(provider: "square", status: "COMPLETED", order: updated)
    }
}

final class LiveAPIService: APIServicing {

    static let shared = LiveAPIService()

    private var baseURL: URL {
        let raw = APIKeyStore.shared.backendURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let url = URL(string: raw), !raw.isEmpty, url.scheme != nil {
            return url
        }
        return URL(string: "https://radar.snapcollectibles.com")!
    }

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

    // MARK: - Menu + Order Ahead

    func fetchMenu(forTruck truckId: UUID, availableOnly: Bool) async throws -> [MenuItem] {
        var components = URLComponents(
            url: baseURL
                .appendingPathComponent("api/trucks")
                .appendingPathComponent(truckId.uuidString)
                .appendingPathComponent("menu"),
            resolvingAgainstBaseURL: false
        )

        if availableOnly {
            components?.queryItems = [URLQueryItem(name: "available_only", value: "true")]
        }

        guard let url = components?.url else { throw APIError.invalidResponse }

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode([MenuItem].self, from: data)
    }

    func createOrder(_ request: NewOrderRequest) async throws -> Order {
        let url = baseURL.appendingPathComponent("api/orders")

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = 20
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder.apiEncoder.encode(request)

        let (data, response) = try await URLSession.shared.data(for: urlRequest)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(Order.self, from: data)
    }

    func fetchOrder(id: String) async throws -> Order {
        let url = baseURL
            .appendingPathComponent("api/orders")
            .appendingPathComponent(id)

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(Order.self, from: data)
    }

    // MARK: - Owner Order Board

    func fetchOrders(forTruck truckId: UUID, activeOnly: Bool) async throws -> [Order] {
        var components = URLComponents(
            url: baseURL
                .appendingPathComponent("api/trucks")
                .appendingPathComponent(truckId.uuidString)
                .appendingPathComponent("orders"),
            resolvingAgainstBaseURL: false
        )

        components?.queryItems = [URLQueryItem(name: "active_only", value: activeOnly ? "true" : "false")]

        guard let url = components?.url else { throw APIError.invalidResponse }

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode([Order].self, from: data)
    }

    func updateOrderStatus(orderId: String, status: OrderStatus, pickupEtaMinutes: Int?) async throws -> Order {
        let url = baseURL
            .appendingPathComponent("api/orders")
            .appendingPathComponent(orderId)
            .appendingPathComponent("status")

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "PATCH"
        urlRequest.timeoutInterval = 20
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")

        struct Body: Encodable {
            var status: String
            var pickupEtaMinutes: Int?
        }

        urlRequest.httpBody = try JSONEncoder.apiEncoder.encode(
            Body(status: status.rawValue, pickupEtaMinutes: pickupEtaMinutes)
        )

        let (data, response) = try await URLSession.shared.data(for: urlRequest)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(Order.self, from: data)
    }

    // MARK: - Payments (Phase 5)

    func fetchPaymentsConfig() async throws -> PaymentsConfig {
        let url = baseURL.appendingPathComponent("api/payments/config")

        let (data, response) = try await URLSession.shared.data(from: url)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(PaymentsConfig.self, from: data)
    }

    func createStripePaymentIntent(orderId: String) async throws -> StripePaymentIntent {
        // appendingPathComponent("a/b") percent-encodes slashes on some
        // iOS versions, so each segment is added separately.
        let url = baseURL
            .appendingPathComponent("api")
            .appendingPathComponent("orders")
            .appendingPathComponent(orderId)
            .appendingPathComponent("payments")
            .appendingPathComponent("stripe")
            .appendingPathComponent("intent")

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = 20
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = Data("{}".utf8)

        let (data, response) = try await URLSession.shared.data(for: urlRequest)

        try validate(response, data: data)

        return try JSONDecoder.apiDecoder.decode(StripePaymentIntent.self, from: data)
    }

    /// sourceId comes from Square's In-App Payments SDK CardEntry flow
    /// (SQIPCardEntryViewController) — never construct this from raw
    /// card details client-side. See docs/PAYMENTS.md.
    func chargeSquare(orderId: String, sourceId: String, verificationToken: String?) async throws -> PaymentResult {
        let url = baseURL
            .appendingPathComponent("api")
            .appendingPathComponent("orders")
            .appendingPathComponent(orderId)
            .appendingPathComponent("payments")
            .appendingPathComponent("square")
            .appendingPathComponent("charge")

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = 20
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder.apiEncoder.encode(
            SquareChargeRequest(sourceId: sourceId, verificationToken: verificationToken)
        )

        let (data, response) = try await URLSession.shared.data(for: urlRequest)

        try validate(response)

        return try JSONDecoder.apiDecoder.decode(PaymentResult.self, from: data)
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

    private func validate(_ response: URLResponse, data: Data? = nil) throws {

        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpError(http.statusCode, detail: APIError.detail(from: data))
        }
    }
}

enum APIError: LocalizedError {

    case invalidResponse
    case httpError(Int, detail: String? = nil)

    var errorDescription: String? {

        switch self {

        case .invalidResponse:
            return "Invalid response from Radar backend."

        case .httpError(let status, let detail):
            if let detail, !detail.isEmpty {
                return "Radar backend returned HTTP \(status): \(detail)"
            }
            return "Radar backend returned HTTP \(status)."
        }
    }

    static func detail(from data: Data?) -> String? {
        guard let data, !data.isEmpty else { return nil }
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = obj["detail"] as? String, !detail.isEmpty {
                return String(detail.prefix(280))
            }
            if let detail = obj["detail"] {
                return String(describing: detail).prefix(280).description
            }
        }
        return String(data: data, encoding: .utf8).map { String($0.prefix(280)) }
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

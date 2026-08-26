import Foundation
import CloudKit
import CryptoKit

/// CloudKit-backed implementation of APIServicing.
///
/// IMPORTANT: CloudKit record names imported by the backend are not UUIDs
/// (for example `truck_a69e350afcd8f5a01d06bf5998af48a7`).  This file therefore
/// converts arbitrary CloudKit record names into stable UUIDs instead of
/// silently dropping every imported Truck/Sighting.
final class CloudKitService: APIServicing {
    static let shared = CloudKitService()

    private let container = CKContainer.default()
    private lazy var publicDB = container.publicCloudDatabase

    // MARK: - Helpers

    private func canonicalTruckID(from raw: String) -> UUID {
        UUID(uuidString: raw) ?? stableUUID(for: raw)
    }

    /// Backend CloudKit web services write TIMESTAMP as epoch milliseconds.
    /// Native iOS writes a Date. Accept both so scheduler sightings show up.
    private func stringList(from record: CKRecord, key: String) -> [String] {
        if let list = record[key] as? [String] {
            return list.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        }
        if let one = record[key] as? String {
            let trimmed = one.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty { return [] }
            if trimmed.contains("\n") {
                return trimmed.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            }
            return [trimmed]
        }
        return []
    }

    private func date(from record: CKRecord, key: String) -> Date? {
        if let date = record[key] as? Date {
            return date
        }
        let value: Double?
        if let number = record[key] as? NSNumber {
            value = number.doubleValue
        } else if let intValue = record[key] as? Int {
            value = Double(intValue)
        } else if let doubleValue = record[key] as? Double {
            value = doubleValue
        } else {
            value = nil
        }
        guard let value else { return nil }
        if value > 1_000_000_000_000 {
            return Date(timeIntervalSince1970: value / 1000)
        }
        if value > 1_000_000_000 {
            return Date(timeIntervalSince1970: value)
        }
        return nil
    }

    private func stableUUID(for recordName: String) -> UUID {
        // SHA-256 gives us 16 deterministic bytes for a UUID-shaped value.
        // We set UUID version/variant bits so the value is a valid RFC-style UUID.
        let digest = SHA256.hash(data: Data(recordName.utf8))
        var bytes = Array(digest.prefix(16))
        bytes[6] = (bytes[6] & 0x0F) | 0x50
        bytes[8] = (bytes[8] & 0x3F) | 0x80
        return UUID(uuid: (
            bytes[0], bytes[1], bytes[2], bytes[3],
            bytes[4], bytes[5], bytes[6], bytes[7],
            bytes[8], bytes[9], bytes[10], bytes[11],
            bytes[12], bytes[13], bytes[14], bytes[15]
        ))
    }

    private func upsert(_ record: CKRecord) async throws {
        try await withCheckedThrowingContinuation { continuation in
            let op = CKModifyRecordsOperation(recordsToSave: [record], recordIDsToDelete: nil)
            op.savePolicy = .changedKeys
            op.qualityOfService = .userInitiated
            op.modifyRecordsResultBlock = { result in
                switch result {
                case .success:
                    continuation.resume()
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
            publicDB.add(op)
        }
    }

    // MARK: - Connection

    func testConnection() async -> Bool {
        do {
            return try await container.accountStatus() == .available
        } catch {
            print("CloudKit account status failed: \(error)")
            return false
        }
    }

    func installRadarSubscription() async {
        let id = "roach-coach-radar-sightings-v1"
        do {
            let subscriptions = try await publicDB.allSubscriptions()
            guard !subscriptions.contains(where: { $0.subscriptionID == id }) else { return }

            let sub = CKQuerySubscription(
                recordType: "Sighting",
                predicate: NSPredicate(value: true),
                subscriptionID: id,
                options: [.firesOnRecordCreation, .firesOnRecordUpdate]
            )
            let info = CKSubscription.NotificationInfo()
            info.title = "Radar update"
            info.alertBody = "A food-truck sighting just hit the radar."
            info.soundName = "default"
            info.shouldBadge = true
            info.desiredKeys = ["truckId", "timestamp"]
            sub.notificationInfo = info
            _ = try await publicDB.save(sub)
        } catch {
            print("Radar subscription setup failed: \(error)")
        }
    }

    // MARK: - Trucks

    func fetchTrucks() async throws -> [Truck] {
        let directory = TruckSocialDirectory.bundledDirectoryTrucks()
        var cloud: [Truck] = []
        do {
            let query = CKQuery(recordType: "Truck", predicate: NSPredicate(value: true))
            // Do not require a Sortable index for name.  That was another source
            // of CloudKit query failures in production.
            let (results, _) = try await publicDB.records(matching: query)
            cloud = results.compactMap { _, result in
                guard case .success(let record) = result else { return nil }
                return truck(from: record)
            }
        } catch {
            print("CloudKit Truck query failed: \(error)")
        }
        return TruckSocialDirectory.mergeCloudKit(cloud, withDirectory: directory)
    }

    func createTruck(_ truck: Truck) async throws {
        let record = CKRecord(recordType: "Truck", recordID: CKRecord.ID(recordName: truck.id.uuidString))
        record["name"] = truck.name
        record["cuisineType"] = truck.cuisineType
        record["socialLinks"] = truck.socialLinks
        record["averageConfidenceScore"] = truck.averageConfidenceScore
        record["menuHighlights"] = truck.menuHighlights
        record["imageURL"] = truck.imageURL
        record["rating"] = truck.rating
        record["averageWaitMinutes"] = truck.averageWaitMinutes
        if !truck.region.isEmpty {
            record["region"] = truck.region
        }
        try await upsert(record)
    }

    private func truck(from record: CKRecord) -> Truck? {
        guard let name = record["name"] as? String else { return nil }
        let id = UUID(uuidString: record.recordID.recordName) ?? stableUUID(for: record.recordID.recordName)
        let image = (record["imageURL"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        var links = stringList(from: record, key: "socialLinks")
        if let handle = (record["instagramHandle"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !handle.isEmpty {
            let url = "https://www.instagram.com/\(handle.trimmingCharacters(in: CharacterSet(charactersIn: "@")))/"
            if !links.contains(where: { $0.localizedCaseInsensitiveContains(handle) }) {
                links.append(url)
            }
        }
        return Truck(
            id: id,
            name: name,
            cuisineType: record["cuisineType"] as? String ?? "",
            socialLinks: links,
            averageConfidenceScore: record["averageConfidenceScore"] as? Double ?? 0.0,
            menuHighlights: record["menuHighlights"] as? [String] ?? [],
            imageURL: (image?.isEmpty == false) ? image : nil,
            rating: record["rating"] as? Double ?? 0.0,
            averageWaitMinutes: record["averageWaitMinutes"] as? Int ?? 15,
            region: record["region"] as? String ?? ""
        )
    }

    // MARK: - Sightings

    func fetchSightings() async throws -> [Sighting] {
        try await fetchSightings(since: Date().addingTimeInterval(-3 * 60 * 60))
    }

    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting] {
        // Do not query `truckId == uuidString`. Backend writes lowercase UUIDs
        // or `truck_…` record names; CloudKit string compare is case-sensitive
        // and UUID(uuidString:) would drop the latter. Fetch the 14-day window
        // and match the same canonical Truck.id the rest of the app uses.
        let window = try await fetchSightings(since: Date().addingTimeInterval(-14 * 24 * 60 * 60))
        return window.filter { $0.truckId == truckId }
    }

    private func fetchSightings(since cutoff: Date) async throws -> [Sighting] {
        let parsed = try await querySightings(
            predicate: NSPredicate(format: "timestamp > %@", cutoff as NSDate)
        )
        if !parsed.isEmpty {
            return parsed.filter { $0.timestamp > cutoff }
        }
        // Older scheduler writes used INT64 millis. A Date predicate can
        // miss those; fall back to an unfiltered query and filter locally.
        let all = try await querySightings(predicate: NSPredicate(value: true))
        return all.filter { $0.timestamp > cutoff }
    }

    private func querySightings(predicate: NSPredicate) async throws -> [Sighting] {
        let query = CKQuery(recordType: "Sighting", predicate: predicate)
        do {
            let (results, _) = try await publicDB.records(matching: query)
            return results.compactMap { _, result in
                guard case .success(let record) = result else { return nil }
                return sighting(from: record)
            }.sorted { $0.timestamp > $1.timestamp }
        } catch {
            print("CloudKit Sighting query failed: \(error)")
            return []
        }
    }

    func submitSighting(_ sighting: Sighting) async throws {
        let recentCount = try await recentSightingCount(forTruck: sighting.truckId)
        let confidence: ConfidenceLevel = recentCount >= 2 ? .confirmed : .likely
        let record = CKRecord(recordType: "Sighting", recordID: CKRecord.ID(recordName: sighting.id.uuidString))
        record["truckId"] = sighting.truckId.uuidString
        record["latitude"] = sighting.latitude
        record["longitude"] = sighting.longitude
        record["note"] = sighting.note
        record["photoURL"] = sighting.photoURL
        record["confidenceLevel"] = confidence.rawValue
        record["timestamp"] = sighting.timestamp
        record["expiresAt"] = sighting.expiresAt
        try await upsert(record)
    }

    private func recentSightingCount(forTruck truckId: UUID) async throws -> Int {
        let cutoff = Date().addingTimeInterval(-60 * 60)
        let query = CKQuery(
            recordType: "Sighting",
            predicate: NSPredicate(format: "truckId == %@ AND timestamp > %@", truckId.uuidString, cutoff as NSDate)
        )
        let (results, _) = try await publicDB.records(matching: query)
        return results.count
    }

    func attachPhoto(_ fileURL: URL, to sightingID: UUID) async throws {
        let record = try await publicDB.record(for: CKRecord.ID(recordName: sightingID.uuidString))
        record["photoAsset"] = CKAsset(fileURL: fileURL)
        try await upsert(record)
    }

    private func sighting(from record: CKRecord) -> Sighting? {
        guard
            let truckIdString = record["truckId"] as? String,
            let latitude = record["latitude"] as? Double,
            let longitude = record["longitude"] as? Double,
            let timestamp = date(from: record, key: "timestamp"),
            let confidenceRaw = record["confidenceLevel"] as? String,
            let confidence = ConfidenceLevel(rawValue: confidenceRaw)
        else { return nil }

        let truckId = canonicalTruckID(from: truckIdString)
        let id = UUID(uuidString: record.recordID.recordName) ?? stableUUID(for: record.recordID.recordName)
        return Sighting(
            id: id,
            truckId: truckId,
            latitude: latitude,
            longitude: longitude,
            photoURL: record["photoURL"] as? String,
            note: record["note"] as? String,
            timestamp: timestamp,
            confidenceLevel: confidence,
            expiresAt: date(from: record, key: "expiresAt")
        )
    }

    // MARK: - User

    func fetchUser() async throws -> AppUser {
        AppUser(displayName: "Family Member", homeCity: "")
    }

    func updateFavorites(_ truckIds: [UUID]) async throws { }

    // MARK: - Menu + Order Ahead

    func fetchMenu(forTruck truckId: UUID, availableOnly: Bool) async throws -> [MenuItem] {
        let records = await queryAll(type: "MenuItem")
        let needle = truckId.uuidString.lowercased()
        var items = records.compactMap { menuItem(from: $0) }.filter {
            $0.truckId.lowercased() == needle
        }
        if items.isEmpty {
            items = MenuCatalog.items(matching: truckId)
        }
        items.sort { $0.sortOrder < $1.sortOrder }
        return availableOnly ? items.filter(\.isAvailable) : items
    }

    func createOrder(_ request: NewOrderRequest) async throws -> Order {
        guard let truckUUID = UUID(uuidString: request.truckId) else {
            throw APIError.httpError(400)
        }
        let menu = try await fetchMenu(forTruck: truckUUID, availableOnly: false)
            var resolved: [OrderLineItem] = []
            var subtotal = 0
            for line in request.items {
                guard let item = menu.first(where: { $0.id == line.menuItemId }) else {
                    continue
                }
                try? await upsertMenuItem(item)
                let delta = line.modifiers.reduce(0) { $0 + $1.priceDeltaCents }
                let unit = item.priceCents + delta
                let total = unit * max(1, line.quantity)
                subtotal += total
                resolved.append(
                    OrderLineItem(
                        menuItemId: item.id,
                        nameSnapshot: item.name,
                        unitPriceCents: item.priceCents,
                        quantity: line.quantity,
                        modifiers: line.modifiers,
                        lineTotalCents: total
                    )
                )
            }
            guard !resolved.isEmpty else { throw APIError.httpError(400) }
            let tax = Int((Double(subtotal) * 0.0875).rounded())
            let now = Date()
            let order = Order(
                id: "order_\(UUID().uuidString.lowercased())",
                truckId: request.truckId,
                customerUserId: request.customerUserId,
                customerName: request.customerName,
                status: .pending,
                items: resolved,
                subtotalCents: subtotal,
                taxCents: tax,
                tipCents: request.tipCents,
                totalCents: subtotal + tax + request.tipCents,
                currency: "USD",
                specialInstructions: request.specialInstructions,
                pickupEtaMinutes: nil,
                paymentProvider: nil,
                paymentStatus: "unpaid",
                createdAt: now,
                updatedAt: now
            )
            try await saveOrder(order)
            return order
    }

    func fetchOrder(id: String) async throws -> Order {
        let recordID = CKRecord.ID(recordName: id)
        do {
            let record = try await publicDB.record(for: recordID)
            if let order = order(from: record) { return order }
        } catch {
            print("CloudKit order lookup failed: \(error)")
        }
        throw APIError.httpError(404)
    }

    func fetchOrders(forTruck truckId: UUID, activeOnly: Bool) async throws -> [Order] {
        let records = await queryAll(type: "Order")
        let needle = truckId.uuidString.lowercased()
        var orders = records.compactMap { order(from: $0) }.filter {
            $0.truckId.lowercased() == needle
        }
        if activeOnly {
            orders = orders.filter { $0.status != .completed && $0.status != .cancelled }
        }
        return orders.sorted { $0.createdAt > $1.createdAt }
    }

    func updateOrderStatus(orderId: String, status: OrderStatus, pickupEtaMinutes: Int?) async throws -> Order {
        var order = try await fetchOrder(id: orderId)
        order.status = status
        order.pickupEtaMinutes = pickupEtaMinutes ?? order.pickupEtaMinutes
        order.updatedAt = Date()
        try await saveOrder(order)
        if status == .ready {
            NotificationService.shared.scheduleTruckSpottedNotification(
                truckName: "Your order",
                note: "Order is ready for pickup.",
                delaySeconds: 1
            )
        }
        return order
    }

    func saveMenuItem(_ item: MenuItem) async throws {
        try await upsertMenuItem(item)
    }

    func deleteMenuItem(id: String) async throws {
        try await publicDB.deleteRecord(withID: CKRecord.ID(recordName: id))
    }

    func fetchPaymentsConfig() async throws -> PaymentsConfig {
        try await LiveAPIService.shared.fetchPaymentsConfig()
    }

    func createStripePaymentIntent(orderId: String) async throws -> StripePaymentIntent {
        try await LiveAPIService.shared.createStripePaymentIntent(orderId: orderId)
    }

    func chargeSquare(orderId: String, sourceId: String, verificationToken: String?) async throws -> PaymentResult {
        try await LiveAPIService.shared.chargeSquare(orderId: orderId, sourceId: sourceId, verificationToken: verificationToken)
    }

    private func queryAll(type: String) async -> [CKRecord] {
        let query = CKQuery(recordType: type, predicate: NSPredicate(value: true))
        do {
            let (results, _) = try await publicDB.records(matching: query)
            return results.compactMap { _, result in
                guard case .success(let record) = result else { return nil }
                return record
            }
        } catch {
            print("CloudKit \(type) query failed: \(error)")
            return []
        }
    }

    private func menuItem(from record: CKRecord) -> MenuItem? {
        guard let name = record["name"] as? String else { return nil }
        let available: Bool
        if let flag = record["isAvailable"] as? Int {
            available = flag != 0
        } else if let flag = record["isAvailable"] as? Int64 {
            available = flag != 0
        } else {
            available = true
        }
        var modifiers: [MenuItemModifier] = []
        if let raw = record["modifiersJSON"] as? String,
           let data = raw.data(using: .utf8),
           let parsed = try? JSONDecoder().decode([MenuItemModifier].self, from: data) {
            modifiers = parsed
        }
        let categoryRaw = record["category"] as? String ?? "entree"
        return MenuItem(
            id: record.recordID.recordName,
            truckId: record["truckID"] as? String ?? "",
            name: name,
            description: record["itemDescription"] as? String,
            category: MenuCategory(rawValue: categoryRaw) ?? .entree,
            priceCents: (record["priceCents"] as? Int) ?? Int(record["priceCents"] as? Int64 ?? 0),
            currency: record["currency"] as? String ?? "USD",
            photoURL: record["photoURL"] as? String,
            isAvailable: available,
            sortOrder: (record["sortOrder"] as? Int) ?? Int(record["sortOrder"] as? Int64 ?? 0),
            modifiers: modifiers
        )
    }

    private func upsertMenuItem(_ item: MenuItem) async throws {
        let record = CKRecord(recordType: "MenuItem", recordID: CKRecord.ID(recordName: item.id))
        record["truckID"] = item.truckId
        record["name"] = item.name
        record["itemDescription"] = item.description
        record["category"] = item.category.rawValue
        record["priceCents"] = item.priceCents
        record["currency"] = item.currency
        record["photoURL"] = item.photoURL
        record["isAvailable"] = item.isAvailable ? 1 : 0
        record["sortOrder"] = item.sortOrder
        if let data = try? JSONEncoder().encode(item.modifiers),
           let json = String(data: data, encoding: .utf8) {
            record["modifiersJSON"] = json
        }
        record["updatedAt"] = Date()
        try await upsert(record)
    }

    private func order(from record: CKRecord) -> Order? {
        guard let truckId = record["truckID"] as? String else { return nil }
        var items: [OrderLineItem] = []
        if let raw = record["itemsJSON"] as? String,
           let data = raw.data(using: .utf8),
           let parsed = try? JSONDecoder().decode([OrderLineItem].self, from: data) {
            items = parsed
        }
        let statusRaw = record["status"] as? String ?? "pending"
        return Order(
            id: record.recordID.recordName,
            truckId: truckId,
            customerUserId: record["customerUserID"] as? String,
            customerName: record["customerName"] as? String,
            status: OrderStatus(rawValue: statusRaw) ?? .pending,
            items: items,
            subtotalCents: (record["subtotalCents"] as? Int) ?? Int(record["subtotalCents"] as? Int64 ?? 0),
            taxCents: (record["taxCents"] as? Int) ?? Int(record["taxCents"] as? Int64 ?? 0),
            tipCents: (record["tipCents"] as? Int) ?? Int(record["tipCents"] as? Int64 ?? 0),
            totalCents: (record["totalCents"] as? Int) ?? Int(record["totalCents"] as? Int64 ?? 0),
            currency: record["currency"] as? String ?? "USD",
            specialInstructions: record["specialInstructions"] as? String,
            pickupEtaMinutes: record["pickupEtaMinutes"] as? Int,
            paymentProvider: record["paymentProvider"] as? String,
            paymentStatus: record["paymentStatus"] as? String ?? "unpaid",
            createdAt: date(from: record, key: "createdAt") ?? Date(),
            updatedAt: date(from: record, key: "updatedAt") ?? Date()
        )
    }

    private func saveOrder(_ order: Order) async throws {
        let record = CKRecord(recordType: "Order", recordID: CKRecord.ID(recordName: order.id))
        record["truckID"] = order.truckId
        record["customerUserID"] = order.customerUserId
        record["customerName"] = order.customerName
        record["status"] = order.status.rawValue
        record["subtotalCents"] = order.subtotalCents
        record["taxCents"] = order.taxCents
        record["tipCents"] = order.tipCents
        record["totalCents"] = order.totalCents
        record["currency"] = order.currency
        record["specialInstructions"] = order.specialInstructions
        if let eta = order.pickupEtaMinutes { record["pickupEtaMinutes"] = eta }
        record["paymentProvider"] = order.paymentProvider
        record["paymentStatus"] = order.paymentStatus
        record["createdAt"] = order.createdAt
        record["createdAtMs"] = Int(order.createdAt.timeIntervalSince1970 * 1000)
        record["updatedAt"] = order.updatedAt
        if let data = try? JSONEncoder().encode(order.items),
           let json = String(data: data, encoding: .utf8) {
            record["itemsJSON"] = json
        }
        try await upsert(record)
    }
}

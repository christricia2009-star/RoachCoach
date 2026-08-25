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
        let query = CKQuery(recordType: "Truck", predicate: NSPredicate(value: true))
        // Do not require a Sortable index for name.  That was another source
        // of CloudKit query failures in production.
        let (results, _) = try await publicDB.records(matching: query)
        return results.compactMap { _, result in
            guard case .success(let record) = result else { return nil }
            return truck(from: record)
        }.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
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
        try await upsert(record)
    }

    private func truck(from record: CKRecord) -> Truck? {
        guard let name = record["name"] as? String else { return nil }
        let id = UUID(uuidString: record.recordID.recordName) ?? stableUUID(for: record.recordID.recordName)
        return Truck(
            id: id,
            name: name,
            cuisineType: record["cuisineType"] as? String ?? "",
            socialLinks: record["socialLinks"] as? [String] ?? [],
            averageConfidenceScore: record["averageConfidenceScore"] as? Double ?? 0.0,
            menuHighlights: record["menuHighlights"] as? [String] ?? [],
            imageURL: record["imageURL"] as? String,
            rating: record["rating"] as? Double ?? 0.0,
            averageWaitMinutes: record["averageWaitMinutes"] as? Int ?? 15
        )
    }

    // MARK: - Sightings

    func fetchSightings() async throws -> [Sighting] {
        let cutoff = Date().addingTimeInterval(-3 * 60 * 60)
        let predicate = NSPredicate(format: "timestamp > %@", cutoff as NSDate)
        let query = CKQuery(recordType: "Sighting", predicate: predicate)
        // No Sortable index required; sort locally.
        let (results, _) = try await publicDB.records(matching: query)
        return results.compactMap { _, result in
            guard case .success(let record) = result else { return nil }
            return sighting(from: record)
        }.sorted { $0.timestamp > $1.timestamp }
    }

    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting] {
        let query = CKQuery(recordType: "Sighting", predicate: NSPredicate(format: "truckId == %@", truckId.uuidString))
        let (results, _) = try await publicDB.records(matching: query)
        return results.compactMap { _, result in
            guard case .success(let record) = result else { return nil }
            return sighting(from: record)
        }.sorted { $0.timestamp > $1.timestamp }
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
            let truckId = UUID(uuidString: truckIdString),
            let latitude = record["latitude"] as? Double,
            let longitude = record["longitude"] as? Double,
            let timestamp = record["timestamp"] as? Date,
            let confidenceRaw = record["confidenceLevel"] as? String,
            let confidence = ConfidenceLevel(rawValue: confidenceRaw)
        else { return nil }

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
            expiresAt: record["expiresAt"] as? Date
        )
    }

    // MARK: - User

    func fetchUser() async throws -> AppUser {
        AppUser(displayName: "Family Member", homeCity: "")
    }

    func updateFavorites(_ truckIds: [UUID]) async throws { }
}

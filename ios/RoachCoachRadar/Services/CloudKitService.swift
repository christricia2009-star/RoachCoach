import Foundation
import CloudKit

/// Interim "backend" using CloudKit's PUBLIC database instead of a hosted
/// Postgres server. Ideal for a family/friends TestFlight app:
///   - Free (well within Apple's CloudKit free tier for this scale)
///   - No server to host, patch, or pay for
///   - Everyone using the app with iCloud signed in reads/writes the same
///     shared data automatically
///
/// Trade-offs vs. the Postgres/FastAPI backend (Backend/main.py):
///   - No PostGIS-style geospatial queries — CloudKit supports a basic
///     `CKLocationSortDescriptor` and radius-style predicates, which is
///     plenty for a single-city family app, but won't scale to
///     multi-city/high-query-volume the way Postgres will.
///   - No custom server-side logic (like the confidence-scoring function
///     in Backend/main.py) — that logic is reimplemented client-side below.
///     Fine for a small trusted user base; revisit if you ever open this
///     to the public, since client-side logic is easier to spoof.
///   - Schema changes happen via CloudKit Dashboard (icloud.developer.apple.com)
///     rather than a schema.sql migration.
///
/// SETUP (one-time, in Xcode):
///   1. Select your app target → Signing & Capabilities → "+ Capability" →
///      add "iCloud" → check "CloudKit".
///   2. Xcode auto-creates a default container
///      (iCloud.com.yourbundleid.RoachCoachRadar).
///   3. Open CloudKit Dashboard, create record types "Truck" and
///      "Sighting" matching the fields below (or just run this code once —
///      CloudKit can infer schema from your first saved records in
///      development environment).
final class CloudKitService: APIServicing {
    static let shared = CloudKitService()

    private let container = CKContainer.default()
    private lazy var publicDB = container.publicCloudDatabase


    // MARK: - Live Radar Push

    /// Creates a public-database subscription for new/updated sightings.
    /// CloudKit delivers the event as a push notification; the app then
    /// refreshes its radar data. Safe to call on every launch.
    func installRadarSubscription() async {
        let subscriptionID = "roach-coach-radar-sightings-v1"
        do {
            let existing = try await publicDB.allSubscriptions()
            if existing.contains(where: { $0.subscriptionID == subscriptionID }) {
                return
            }

            let info = CKSubscription.NotificationInfo()
            info.title = "Radar update"
            info.alertBody = "A food-truck sighting just hit the radar."
            info.soundName = "default"
            info.shouldBadge = true
            info.desiredKeys = ["truckId", "timestamp"]

            let subscription = CKQuerySubscription(
                recordType: "Sighting",
                predicate: NSPredicate(value: true),
                subscriptionID: subscriptionID,
                options: [.firesOnRecordCreation, .firesOnRecordUpdate]
            )
            subscription.notificationInfo = info
            _ = try await publicDB.save(subscription)
        } catch {
            print("Radar subscription setup: \(error)")
        }
    }

    // MARK: - Trucks

    func fetchTrucks() async throws -> [Truck] {
        let query = CKQuery(recordType: "Truck", predicate: NSPredicate(value: true))
        query.sortDescriptors = [NSSortDescriptor(key: "name", ascending: true)]

        let (matchResults, _) = try await publicDB.records(matching: query)
        return matchResults.compactMap { _, result in
            guard case .success(let record) = result else { return nil }
            return truck(from: record)
        }
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
        _ = try await publicDB.save(record)
    }

    private func truck(from record: CKRecord) -> Truck? {
        guard
            let name = record["name"] as? String,
            let recordName = UUID(uuidString: record.recordID.recordName)
        else { return nil }

        return Truck(
            id: recordName,
            name: name,
            cuisineType: record["cuisineType"] as? String ?? "",
            socialLinks: record["socialLinks"] as? [String] ?? [],
            averageConfidenceScore: record["averageConfidenceScore"] as? Double ?? 0.0,
            menuHighlights: record["menuHighlights"] as? [String] ?? [],
            imageURL: record["imageURL"] as? String,
            rating: record["rating"] as? Double ?? 4.5,
            averageWaitMinutes: record["averageWaitMinutes"] as? Int ?? 8
        )
    }

    // MARK: - Sightings

    func fetchSightings() async throws -> [Sighting] {
        let cutoff = Date().addingTimeInterval(-3 * 60 * 60)
        let predicate = NSPredicate(format: "timestamp > %@", cutoff as NSDate)
        let query = CKQuery(recordType: "Sighting", predicate: predicate)
        query.sortDescriptors = [NSSortDescriptor(key: "timestamp", ascending: false)]

        let (matchResults, _) = try await publicDB.records(matching: query)
        return matchResults.compactMap { _, result in
            guard case .success(let record) = result else { return nil }
            return sighting(from: record)
        }
    }

    func fetchSightings(forTruck truckId: UUID) async throws -> [Sighting] {
        let predicate = NSPredicate(format: "truckId == %@", truckId.uuidString)
        let query = CKQuery(recordType: "Sighting", predicate: predicate)
        query.sortDescriptors = [NSSortDescriptor(key: "timestamp", ascending: false)]

        let (matchResults, _) = try await publicDB.records(matching: query)
        return matchResults.compactMap { _, result in
            guard case .success(let record) = result else { return nil }
            return sighting(from: record)
        }
    }

    /// Uploads a photo as a CloudKit asset when the deployed Sighting schema has a photoAsset field.
    /// Safe to leave unused until that field is added in CloudKit Dashboard.
    func attachPhoto(_ fileURL: URL, to sightingID: UUID) async throws {
        let recordID = CKRecord.ID(recordName: sightingID.uuidString)
        let record = try await publicDB.record(for: recordID)
        record["photoAsset"] = CKAsset(fileURL: fileURL)
        _ = try await publicDB.save(record)
    }

    func submitSighting(_ sighting: Sighting) async throws {
        // Reimplements the same confidence-scoring heuristic as
        // Backend/main.py's compute_confidence(), client-side, since there's
        // no server here to run it centrally.
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

        _ = try await publicDB.save(record)
    }

    private func recentSightingCount(forTruck truckId: UUID) async throws -> Int {
        let cutoff = Date().addingTimeInterval(-60 * 60)
        let predicate = NSPredicate(
            format: "truckId == %@ AND timestamp > %@",
            truckId.uuidString, cutoff as NSDate
        )
        let query = CKQuery(recordType: "Sighting", predicate: predicate)
        let (matchResults, _) = try await publicDB.records(matching: query)
        return matchResults.count
    }

    private func sighting(from record: CKRecord) -> Sighting? {
        guard
            let truckIdString = record["truckId"] as? String,
            let truckId = UUID(uuidString: truckIdString),
            let recordId = UUID(uuidString: record.recordID.recordName),
            let latitude = record["latitude"] as? Double,
            let longitude = record["longitude"] as? Double,
            let timestamp = record["timestamp"] as? Date,
            let confidenceRaw = record["confidenceLevel"] as? String,
            let confidence = ConfidenceLevel(rawValue: confidenceRaw)
        else { return nil }

        return Sighting(
            id: recordId,
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

    // MARK: - Users (kept local for now — CloudKit's private DB per-user
    // model doesn't map cleanly onto the shared AppUser concept without
    // more design work than a family app needs yet)

    func fetchUser() async throws -> AppUser {
        AppUser(displayName: "Family Member", homeCity: "")
    }

    func updateFavorites(_ truckIds: [UUID]) async throws {
        // No-op for now — favorites can stay device-local (UserDefaults)
        // until/unless you want them synced across a user's own devices via
        // CloudKit's private database.
    }
}

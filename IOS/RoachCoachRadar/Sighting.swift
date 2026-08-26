import Foundation
import CoreLocation

enum ConfidenceLevel: String, Codable, CaseIterable {
    // Backend (backend/main.py compute_confidence, and the
    // confidenceLevel default on RadarSightingOut) emits lowercase
    // "confirmed"/"likely"/"scheduled". These raw values previously
    // required a capitalized "Confirmed"/"Likely"/"Scheduled", which
    // Swift enums with String raw values reject on any non-exact match
    // — same failure mode as the SourceKind.telecom bug: one
    // unrecognized case value breaks Codable for that record.
    //
    // Custom init?(rawValue:) below matches case-insensitively instead
    // of relying on the compiler-synthesized exact-match initializer,
    // so this also keeps decoding any Sighting records CloudKitService
    // already wrote under the OLD capitalized raw values (native
    // CKRecord writes are a separate path from this REST API — see
    // ARCHITECTURE.md's note on the two write paths drifting) instead
    // of silently dropping them going forward. Use
    // ConfidenceLevel.displayName wherever UI needs Title Case.
    case confirmed = "confirmed"
    case likely = "likely"
    case scheduled = "scheduled"

    init?(rawValue: String) {
        switch rawValue.lowercased() {
        case "confirmed": self = .confirmed
        case "likely": self = .likely
        case "scheduled": self = .scheduled
        default: return nil
        }
    }

    var displayName: String {
        switch self {
        case .confirmed: return "Confirmed"
        case .likely: return "Likely"
        case .scheduled: return "Scheduled"
        }
    }

    var sortWeight: Int {
        switch self {
        case .confirmed: return 3
        case .likely: return 2
        case .scheduled: return 1
        }
    }
}

struct Sighting: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    var truckId: UUID
    var latitude: Double
    var longitude: Double
    var reportedByUserId: UUID?
    var photoURL: String?
    var note: String?
    var timestamp: Date
    var confidenceLevel: ConfidenceLevel
    var expiresAt: Date

    var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    var isExpired: Bool {
        Date() > expiresAt
    }

    init(
        id: UUID = UUID(),
        truckId: UUID,
        latitude: Double,
        longitude: Double,
        reportedByUserId: UUID? = nil,
        photoURL: String? = nil,
        note: String? = nil,
        timestamp: Date = Date(),
        confidenceLevel: ConfidenceLevel = .likely,
        expiresAt: Date? = nil
    ) {
        self.id = id
        self.truckId = truckId
        self.latitude = latitude
        self.longitude = longitude
        self.reportedByUserId = reportedByUserId
        self.photoURL = photoURL
        self.note = note
        self.timestamp = timestamp
        self.confidenceLevel = confidenceLevel
        self.expiresAt = expiresAt ?? timestamp.addingTimeInterval(3 * 60 * 60) // 3 hour default expiry
    }
}

extension Array where Element == Sighting {
    /// Newest first, same pin collapsed, capped at `limit`.
    func uniqueRecent(limit: Int = 5, meters: CLLocationDistance = 150) -> [Sighting] {
        let sorted = sorted { $0.timestamp > $1.timestamp }
        var kept: [Sighting] = []
        for sighting in sorted {
            let here = CLLocation(latitude: sighting.latitude, longitude: sighting.longitude)
            let duplicate = kept.contains { existing in
                let there = CLLocation(latitude: existing.latitude, longitude: existing.longitude)
                return there.distance(from: here) < meters
            }
            if !duplicate {
                kept.append(sighting)
                if kept.count == limit { break }
            }
        }
        return kept
    }
}

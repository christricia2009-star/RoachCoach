import Foundation
import CoreLocation

enum ConfidenceLevel: String, Codable, CaseIterable {
    case confirmed = "Confirmed"
    case likely = "Likely"
    case scheduled = "Scheduled"

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

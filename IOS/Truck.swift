import Foundation
import CoreLocation

struct Truck: Identifiable, Codable, Hashable {
    let id: UUID
    var name: String
    var cuisineType: String
    var socialLinks: [String]
    var averageConfidenceScore: Double
    var menuHighlights: [String]
    var imageURL: String?
    var rating: Double
    var averageWaitMinutes: Int

    // Backend (backend/main.py TruckOut) has no alias_generator, so it
    // serializes plain Python snake_case field names — cuisine_type,
    // social_links, average_confidence_score, image_url — not
    // cuisineType/socialLinks/averageConfidenceScore/imageURL. Without
    // this CodingKeys mapping, JSONDecoder looks for the camelCase keys
    // verbatim, finds none of them, and [Truck] decode throws
    // keyNotFound on the very first record — the whole /api/trucks
    // response is unusable. `rating` and `averageWaitMinutes` don't
    // exist in TruckOut at all yet, so they're decoded via
    // decodeIfPresent below with the same defaults the memberwise
    // init uses, instead of being required keys that would break
    // decoding entirely the moment they're absent.
    enum CodingKeys: String, CodingKey {
        case id
        case name
        case cuisineType = "cuisine_type"
        case socialLinks = "social_links"
        case averageConfidenceScore = "average_confidence_score"
        case menuHighlights = "menu_highlights"
        case imageURL = "image_url"
        case rating
        case averageWaitMinutes = "average_wait_minutes"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        cuisineType = try container.decode(String.self, forKey: .cuisineType)
        socialLinks = try container.decodeIfPresent([String].self, forKey: .socialLinks) ?? []
        averageConfidenceScore = try container.decodeIfPresent(Double.self, forKey: .averageConfidenceScore) ?? 0.0
        menuHighlights = try container.decodeIfPresent([String].self, forKey: .menuHighlights) ?? []
        imageURL = try container.decodeIfPresent(String.self, forKey: .imageURL)
        rating = try container.decodeIfPresent(Double.self, forKey: .rating) ?? 4.5
        averageWaitMinutes = try container.decodeIfPresent(Int.self, forKey: .averageWaitMinutes) ?? 8
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(name, forKey: .name)
        try container.encode(cuisineType, forKey: .cuisineType)
        try container.encode(socialLinks, forKey: .socialLinks)
        try container.encode(averageConfidenceScore, forKey: .averageConfidenceScore)
        try container.encode(menuHighlights, forKey: .menuHighlights)
        try container.encodeIfPresent(imageURL, forKey: .imageURL)
        try container.encode(rating, forKey: .rating)
        try container.encode(averageWaitMinutes, forKey: .averageWaitMinutes)
    }

    init(
        id: UUID = UUID(),
        name: String,
        cuisineType: String,
        socialLinks: [String] = [],
        averageConfidenceScore: Double = 0.0,
        menuHighlights: [String] = [],
        imageURL: String? = nil,
        rating: Double = 4.5,
        averageWaitMinutes: Int = 8
    ) {
        self.id = id
        self.name = name
        self.cuisineType = cuisineType
        self.socialLinks = socialLinks
        self.averageConfidenceScore = averageConfidenceScore
        self.menuHighlights = menuHighlights
        self.imageURL = imageURL
        self.rating = rating
        self.averageWaitMinutes = averageWaitMinutes
    }
}

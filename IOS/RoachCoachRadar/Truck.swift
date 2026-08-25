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

struct TruckSocialLink: Identifiable, Hashable {
    let id: String
    let title: String
    let handle: String
    let url: URL
    let systemImage: String
}

enum TruckSocialDirectory {
    private struct Profile {
        let match: String
        let instagram: String?
        let x: String?
        let facebook: String?
        let website: String?
    }

    private static let profiles: [Profile] = [
        .init(match: "drewski", instagram: "drewskis", x: "drewskis", facebook: "drewskisfoodtrucks", website: "https://drewskis.com"),
        .init(match: "buckhorn", instagram: "thebuckhornbbqtruck", x: "thebuckhornbbqtruck", facebook: "thebuckhornbbqtruck", website: nil),
        .init(match: "sactomofo", instagram: "sactomofo", x: "sactomofo", facebook: "sactomofo", website: nil),
        .init(match: "krush", instagram: "krushroseville", x: "krushroseville", facebook: "krushroseville", website: nil),
        .init(match: "potato", instagram: "the_potato_truck", x: "the_potato_truck", facebook: "the_potato_truck", website: nil),
        .init(match: "alameda taco", instagram: "alamedatacossac", x: "alamedatacossac", facebook: "alamedatacossac", website: nil),
        .init(match: "mucho nacho", instagram: "muchonachossacramento", x: "muchonachossacramento", facebook: "muchonachossacramento", website: nil),
        .init(match: "pop up", instagram: "sactopopuptruck", x: "sactopopuptruck", facebook: "sactopopuptruck", website: nil),
        .init(match: "santacos", instagram: "santacosmx", x: "santacosmx", facebook: "santacosmx", website: nil),
        .init(match: "tacoa", instagram: "tacoasac", x: "tacoasac", facebook: "tacoasac", website: nil),
        .init(match: "tacos gto", instagram: "tacos_gto_", x: "tacos_gto_", facebook: "tacos_gto_", website: nil),
        .init(match: "tacomiendo", instagram: "tacomiendofoodtruck", x: "tacomiendofoodtruck", facebook: "tacomiendofoodtruck", website: nil),
        .init(match: "sac tacos", instagram: "sactacosfoodtruck", x: "sactacosfoodtruck", facebook: "sactacosfoodtruck", website: nil),
        .init(match: "lumpia", instagram: "thelumpiatruck", x: "thelumpiatruck", facebook: "thelumpiatruck", website: nil)
    ]

    static func links(for truck: Truck) -> [TruckSocialLink] {
        var links: [TruckSocialLink] = []
        var seen = Set<String>()

        func append(_ title: String, handle: String, urlString: String, image: String) {
            guard let url = URL(string: urlString) else { return }
            let id = url.absoluteString.lowercased()
            guard seen.insert(id).inserted else { return }
            links.append(
                TruckSocialLink(
                    id: id,
                    title: title,
                    handle: handle.hasPrefix("@") ? handle : "@\(handle)",
                    url: url,
                    systemImage: image
                )
            )
        }

        if let profile = profiles.first(where: { truck.name.localizedCaseInsensitiveContains($0.match) }) {
            if let handle = profile.instagram {
                append("Instagram", handle: handle, urlString: "https://www.instagram.com/\(handle)/", image: "camera")
            }
            if let handle = profile.x {
                append("X", handle: handle, urlString: "https://x.com/\(handle)", image: "bubble.left.and.bubble.right")
            }
            if let handle = profile.facebook {
                append("Facebook", handle: handle, urlString: "https://www.facebook.com/\(handle)", image: "person.2")
            }
            if let website = profile.website {
                append("Website", handle: website.replacingOccurrences(of: "https://", with: ""), urlString: website, image: "globe")
            }
        }

        for raw in truck.socialLinks {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let url = socialURL(from: trimmed) else { continue }
            let host = url.host?.lowercased() ?? ""
            let title: String
            let image: String
            if host.contains("instagram") {
                title = "Instagram"
                image = "camera"
            } else if host.contains("x.com") || host.contains("twitter") {
                title = "X"
                image = "bubble.left.and.bubble.right"
            } else if host.contains("facebook") {
                title = "Facebook"
                image = "person.2"
            } else {
                title = "Website"
                image = "globe"
            }
            append(title, handle: trimmed, urlString: url.absoluteString, image: image)
        }

        return links
    }

    static func seededURLStrings(forName name: String) -> [String] {
        links(for: Truck(name: name, cuisineType: "")).map(\.url.absoluteString)
    }

    private static func socialURL(from raw: String) -> URL? {
        if raw.hasPrefix("http://") || raw.hasPrefix("https://") {
            return URL(string: raw)
        }
        if raw.contains("instagram.com") || raw.contains("x.com") || raw.contains("facebook.com") {
            return URL(string: "https://\(raw)")
        }
        if raw.hasPrefix("@") {
            let handle = String(raw.dropFirst())
            return URL(string: "https://www.instagram.com/\(handle)/")
        }
        return URL(string: "https://www.instagram.com/\(raw)/")
    }
}

struct TruckHoursStatus {
    let summary: String
    let isOpen: Bool?

    var badge: String {
        switch isOpen {
        case true: return "Open now"
        case false: return "Closed now"
        case nil: return "Hours on social"
        }
    }
}

enum TruckHoursDirectory {
    private struct Spec {
        let match: String
        let weekdayStart: Int
        let weekdayEnd: Int
        let openMinutes: Int
        let closeMinutes: Int
        let closedWeekdays: Set<Int>
        let summary: String
    }

    private static let specs: [Spec] = [
        .init(match: "drewski", weekdayStart: 2, weekdayEnd: 6, openMinutes: 10 * 60 + 30, closeMinutes: 15 * 60, closedWeekdays: [1, 7], summary: "Mon–Fri 10:30 AM–3:00 PM")
    ]

    static func status(for truck: Truck, now: Date = Date()) -> TruckHoursStatus {
        let calendar = Calendar.current
        let weekday = calendar.component(.weekday, from: now)
        let minutes = calendar.component(.hour, from: now) * 60 + calendar.component(.minute, from: now)
        if let spec = specs.first(where: { truck.name.localizedCaseInsensitiveContains($0.match) }) {
            if spec.closedWeekdays.contains(weekday) {
                return TruckHoursStatus(summary: spec.summary, isOpen: false)
            }
            let open = minutes >= spec.openMinutes && minutes < spec.closeMinutes
            return TruckHoursStatus(summary: spec.summary, isOpen: open)
        }
        return TruckHoursStatus(summary: "Follow on Instagram for today’s hours", isOpen: nil)
    }
}

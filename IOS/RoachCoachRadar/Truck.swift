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
    var region: String

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
        case region
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
        region = try container.decodeIfPresent(String.self, forKey: .region) ?? TruckSocialDirectory.region(forName: name)
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
        try container.encode(region, forKey: .region)
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
        averageWaitMinutes: Int = 8,
        region: String = ""
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
        self.region = region.isEmpty ? TruckSocialDirectory.region(forName: name) : region
    }

    var socialImageURL: URL? {
        guard let raw = imageURL?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else {
            return nil
        }
        return URL(string: raw)
    }

    var hasSocialPresence: Bool {
        let links = TruckSocialDirectory.links(for: self)
        if links.contains(where: { $0.title == "Instagram" || $0.title == "Facebook" }) {
            return true
        }
        return socialLinks.contains { raw in
            let lower = raw.lowercased()
            return lower.contains("instagram") || lower.contains("facebook") || lower.hasPrefix("@")
        }
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
        let region: String
    }

    static let regionOrder = ["Sacramento", "Bay Area", "North State", "Central Valley", "Central Coast", "Other"]

    private static let profiles: [Profile] = [
        .init(match: "drewski", instagram: "drewskis", x: "drewskishotrod", facebook: "drewskisfoodtrucks", website: "https://drewskis.com", region: "Sacramento"),
        .init(match: "buckhorn", instagram: "thebuckhornbbqtruck", x: nil, facebook: "thebuckhornbbqtruck", website: nil, region: "Sacramento"),
        .init(match: "sactomofo", instagram: "sactomofo", x: "SactoMoFo", facebook: "sactomofo", website: nil, region: "Sacramento"),
        .init(match: "krush", instagram: "krushroseville", x: nil, facebook: "krushroseville", website: nil, region: "Sacramento"),
        .init(match: "potato", instagram: "the_potato_truck", x: nil, facebook: "the_potato_truck", website: nil, region: "Sacramento"),
        .init(match: "alameda taco", instagram: "alamedatacossac", x: nil, facebook: "alamedatacossac", website: nil, region: "Sacramento"),
        .init(match: "mucho nacho", instagram: "muchonachossacramento", x: nil, facebook: "muchonachossacramento", website: nil, region: "Sacramento"),
        .init(match: "pop up", instagram: "sactopopuptruck", x: nil, facebook: "sactopopuptruck", website: nil, region: "Sacramento"),
        .init(match: "santacos", instagram: "santacosmx", x: nil, facebook: "santacosmx", website: nil, region: "Sacramento"),
        .init(match: "tacoa", instagram: "tacoasac", x: nil, facebook: "tacoasac", website: nil, region: "Sacramento"),
        .init(match: "tacos gto", instagram: "tacos_gto_", x: nil, facebook: "tacos_gto_", website: nil, region: "Sacramento"),
        .init(match: "tacomiendo", instagram: "tacomiendofoodtruck", x: nil, facebook: "tacomiendofoodtruck", website: nil, region: "Sacramento"),
        .init(match: "sac tacos", instagram: "sactacosfoodtruck", x: nil, facebook: "sactacosfoodtruck", website: nil, region: "Sacramento"),
        .init(match: "lumpia", instagram: "thelumpiatruck", x: "TheLumpiaTruck", facebook: "thelumpiatruck", website: nil, region: "Sacramento"),
        .init(match: "hefty gyro", instagram: "heftygyros", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "chando", instagram: "chandostacos", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "local kine", instagram: "localkineshaveice", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "west coast taco", instagram: "westcoasttacobar", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "philly", instagram: "thephillyfoodtruck", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "kado", instagram: "kadosasiangrill", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "laopino", instagram: "laopinokitchen", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "palbq", instagram: "palbqsmokehouse", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "smokinewe", instagram: "smokinewebbq", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "birria boys", instagram: "birriaboys", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "authentic street", instagram: "authenticstreettaco", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "gondo fusion", instagram: "gondofusion", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "gameday grill", instagram: "gamedaygrill_", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "island fin", instagram: "ifpcdeltashores", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "bokhoking", instagram: "bokhoking", x: nil, facebook: nil, website: nil, region: "Sacramento"),
        .init(match: "senor sisig", instagram: "senorsisig", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "chairman", instagram: "chairmantruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "curry up", instagram: "curryupnow", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "koja", instagram: "koja_kitchen", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "liba falafel", instagram: "libafalafel", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "adobo bite", instagram: "adobobite", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "hons wonton", instagram: "honswontonpantry", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "kasa indian", instagram: "kasaindian", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "cousins maine", instagram: "cousinsmainelobster", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "roli roti", instagram: "roliroti", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "frogo", instagram: "frogofoodtruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "cochinita", instagram: "cochinita.sf", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "poke man", instagram: "da_poke_man", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "meso hungry", instagram: "mesohungrytoo", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "corn dog", instagram: "worldfamouscorndogs", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "la churroteka", instagram: "lachurroteka", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "food truck mafia", instagram: "thefoodtruckmafia", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "guzz co", instagram: "theguzzco", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "los rockeros", instagram: "losrockeros_foodtruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "crazy empanadas", instagram: "crazyempanadas", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "charlie", instagram: "charliesfoodtrailer", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "baby o", instagram: "babyosdonuts", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "bubble hive", instagram: "bubblehives", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "taco loco", instagram: "elgrantacoloco", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "munchiez", instagram: "bayarea_munchiez", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "capelo", instagram: "capelosbarbecue", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "wokitchen", instagram: "wokitchen_truck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "soco kitchen", instagram: "socokitchen", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "korean bobcha", instagram: "bobchasf", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "respectable bird", instagram: "respectablebird", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "melina", instagram: "melinaskitchen_llc", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "dominic", instagram: "dominicsfoodtruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "golden gate", instagram: "goldengategyro", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "curveball sliders", instagram: "curveballmobile", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "bombzies bbq", instagram: "bombziesbbq", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "global catering", instagram: "globalcateringexpress", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "mozzeria", instagram: "mozzeriasf", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "rosie", instagram: "rosiesmexicanfood", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "chowder", instagram: "samschowdermobile", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "fresh catch", instagram: "freshcatchpoke", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "rincon del", instagram: "rincon_del_cielo_taqueria", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "jolly", instagram: "jollysteascream", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "el gallo", instagram: "elgallogirotruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "grub truck", instagram: "adamsgrubtruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "bunbao", instagram: "bunbaoofficial", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "hula", instagram: "hulatruck408", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "jeepsilog", instagram: "jeepsilog", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "santa torta", instagram: "santatortasf", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "lobsta sf", instagram: "lobstatrucksf", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "momolicious", instagram: "momolicioussf", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "sip n slurp", instagram: "sipnslurpfoodtruck", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "cielito lindo", instagram: "cielitolindomsk", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "kabob trolley", instagram: "kabobtrolley", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "daisy", instagram: "daisysdesserts", x: nil, facebook: nil, website: nil, region: "Bay Area"),
        .init(match: "get rad", instagram: "getradpizza", x: nil, facebook: nil, website: nil, region: "North State"),
        .init(match: "food coma", instagram: "bigcsfoodcoma", x: nil, facebook: nil, website: nil, region: "North State"),
        .init(match: "granny", instagram: "grannysgrillfilipinofoodtruck", x: nil, facebook: nil, website: nil, region: "North State"),
        .init(match: "dos amigos", instagram: "dosamigostaq", x: nil, facebook: nil, website: nil, region: "North State"),
        .init(match: "where's the food", instagram: "wtfwheresthefoodfresno", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "brickology pizza", instagram: "brickologypizza", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "el premio", instagram: "elpremiomayor", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "tacos la", instagram: "tacos_lavaporera", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "sticky rice", instagram: "stickyriceonwheels_fresno", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "taco pinto", instagram: "tacopinto1", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "fresno cheesesteak", instagram: "fresno_cheesesteak", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "get baked", instagram: "getbaked559", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "sno cafe", instagram: "snocafe", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "rolling donut", instagram: "therollingdonutfresno", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "tacos el", instagram: "tacos_el_rey_azteca", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "nikki", instagram: "nikkiscreateabowl", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "tacos la palmita", instagram: "tacoslapalmita209", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "tacos la unica", instagram: "tacoslaunica", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "birrieria chito", instagram: "birrieria_chito", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "tortas ahogadas", instagram: "tortasahogadas_elcejarin", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "food fix", instagram: "foodfixtruck", x: nil, facebook: nil, website: nil, region: "Central Valley"),
        .init(match: "funk", instagram: "funksfranks", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "happy dog", instagram: "happydog_hotdogs", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "hot birds", instagram: "hot_birds831", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "sandwiches burgers", instagram: "snb_foodtruck", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "2 chx", instagram: "two_chx", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "adobo2go", instagram: "adobo2go", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "holopono", instagram: "holoponosc", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "masarap", instagram: "masarapthehomie", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "yakitori toriman", instagram: "yakitori_toriman", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "mariposa cuban", instagram: "mariposacubancoffee", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "dos hermanos", instagram: "dos_hermanos_pupuseria", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "rey leon", instagram: "elreyleon_mexicanfood", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "la perrona", instagram: "_laperrona", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "miches ceviches", instagram: "michesandceviches", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "real taco", instagram: "realtaco56", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "tacos el chuy", instagram: "tacoselchuy", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "tacos el jerry", instagram: "tacoseljerry", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "taquizas gabriel", instagram: "taquizasgabriel", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "huda", instagram: "hudasantacruz", x: nil, facebook: nil, website: nil, region: "Central Coast"),
        .init(match: "mattia pizza", instagram: "mattiapizza04", x: nil, facebook: nil, website: nil, region: "Central Coast"),
    ]


    static func region(forName name: String) -> String {
        profile(matching: name)?.region ?? "Other"
    }

    private static func profile(matching name: String) -> Profile? {
        profiles
            .filter { name.localizedCaseInsensitiveContains($0.match) }
            .max(by: { $0.match.count < $1.match.count })
    }

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

        if let profile = profile(matching: truck.name) {
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

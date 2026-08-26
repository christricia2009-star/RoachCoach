import Foundation

/// A single sellable item on a truck's menu.
///
/// Matches backend/main.py's `MenuItemOut`, which uses populate_by_name +
/// camelCase aliases (the SightingOut convention) — so, unlike Truck.swift,
/// this does NOT need a snake_case CodingKeys workaround. The wire keys are
/// already `truckId`, `priceCents`, `photoURL`, `isAvailable`, `sortOrder`.
struct MenuItemModifier: Codable, Hashable {
    var name: String
    var priceDeltaCents: Int

    enum CodingKeys: String, CodingKey {
        case name
        case priceDeltaCents
    }

    init(name: String, priceDeltaCents: Int = 0) {
        self.name = name
        self.priceDeltaCents = priceDeltaCents
    }
}

enum MenuCategory: String, Codable, CaseIterable, Hashable {
    case entree, side, drink, dessert, combo, special

    var displayName: String {
        switch self {
        case .entree: return "Entrées"
        case .side: return "Sides"
        case .drink: return "Drinks"
        case .dessert: return "Desserts"
        case .combo: return "Combos"
        case .special: return "Specials"
        }
    }
}

struct MenuItem: Identifiable, Codable, Hashable {
    let id: String
    var truckId: String
    var name: String
    var description: String?
    var category: MenuCategory
    var priceCents: Int
    var currency: String
    var photoURL: String?
    var isAvailable: Bool
    var sortOrder: Int
    var modifiers: [MenuItemModifier]

    enum CodingKeys: String, CodingKey {
        case id, truckId, name, description, category
        case priceCents, currency, photoURL, isAvailable, sortOrder, modifiers
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        truckId = try container.decode(String.self, forKey: .truckId)
        name = try container.decode(String.self, forKey: .name)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        // Tolerate a category the client doesn't recognize yet (server adds
        // one first) instead of failing to decode the whole menu.
        if let raw = try? container.decode(String.self, forKey: .category),
           let known = MenuCategory(rawValue: raw) {
            category = known
        } else {
            category = .entree
        }
        priceCents = try container.decode(Int.self, forKey: .priceCents)
        currency = try container.decodeIfPresent(String.self, forKey: .currency) ?? "USD"
        photoURL = try container.decodeIfPresent(String.self, forKey: .photoURL)
        isAvailable = try container.decodeIfPresent(Bool.self, forKey: .isAvailable) ?? true
        sortOrder = try container.decodeIfPresent(Int.self, forKey: .sortOrder) ?? 0
        modifiers = try container.decodeIfPresent([MenuItemModifier].self, forKey: .modifiers) ?? []
    }

    init(
        id: String = UUID().uuidString,
        truckId: String,
        name: String,
        description: String? = nil,
        category: MenuCategory = .entree,
        priceCents: Int,
        currency: String = "USD",
        photoURL: String? = nil,
        isAvailable: Bool = true,
        sortOrder: Int = 0,
        modifiers: [MenuItemModifier] = []
    ) {
        self.id = id
        self.truckId = truckId
        self.name = name
        self.description = description
        self.category = category
        self.priceCents = priceCents
        self.currency = currency
        self.photoURL = photoURL
        self.isAvailable = isAvailable
        self.sortOrder = sortOrder
        self.modifiers = modifiers
    }

    var priceDisplay: String {
        String(format: "$%.2f", Double(priceCents) / 100.0)
    }
}

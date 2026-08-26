import Foundation

/// Starter menus so Order Ahead works before CloudKit MenuItem records exist.
enum MenuCatalog {
    static func items(matching truckId: UUID) -> [MenuItem] {
        let truck = TruckSocialDirectory.bundledDirectoryTrucks().first { $0.id == truckId }
        let cuisine = (truck?.cuisineType ?? "").lowercased()
        let handle = truck?.instagramHandle ?? "menu"
        return template(cuisine: cuisine, handle: handle, truckId: truckId.uuidString)
    }

    private static func template(cuisine: String, handle: String, truckId: String) -> [MenuItem] {
        func item(_ name: String, _ category: MenuCategory, _ cents: Int, _ order: Int, _ description: String? = nil, mods: [MenuItemModifier] = []) -> MenuItem {
            MenuItem(
                id: "menu_\(handle)_\(order)",
                truckId: truckId,
                name: name,
                description: description,
                category: category,
                priceCents: cents,
                sortOrder: order,
                modifiers: mods
            )
        }

        if cuisine.contains("taco") || cuisine.contains("mexican") || cuisine.contains("yucatecan") {
            return [
                item("Street tacos (3)", .entree, 1200, 0, "Cilantro, onion, salsa"),
                item("Quesabirria", .entree, 1400, 1, "Consommé on the side"),
                item("Elote", .side, 600, 2),
                item("Agua fresca", .drink, 400, 3)
            ]
        }
        if cuisine.contains("filipino") {
            return [
                item("Sisig taco", .entree, 1100, 0),
                item("Lumpia (5)", .side, 800, 1),
                item("Garlic rice", .side, 500, 2),
                item("Calamansi drink", .drink, 400, 3)
            ]
        }
        if cuisine.contains("bbq") {
            return [
                item("Brisket plate", .entree, 1800, 0),
                item("Pulled pork sandwich", .entree, 1400, 1),
                item("Mac & cheese", .side, 600, 2),
                item("Iced tea", .drink, 300, 3)
            ]
        }
        if cuisine.contains("pizza") {
            return [
                item("Margherita slice", .entree, 700, 0),
                item("Pepperoni slice", .entree, 800, 1),
                item("Garlic knots", .side, 500, 2),
                item("Soda", .drink, 300, 3)
            ]
        }
        if cuisine.contains("hawaiian") || cuisine.contains("poke") {
            return [
                item("Poke bowl", .entree, 1600, 0, mods: [MenuItemModifier(name: "Extra ahi", priceDeltaCents: 300)]),
                item("Spam musubi", .side, 500, 1),
                item("Shave ice", .dessert, 700, 2)
            ]
        }
        if cuisine.contains("indian") {
            return [
                item("Tikka masala burrito", .entree, 1400, 0),
                item("Samosa (2)", .side, 600, 1),
                item("Mango lassi", .drink, 500, 2)
            ]
        }
        if cuisine.contains("greek") || cuisine.contains("mediterranean") {
            return [
                item("Gyro plate", .entree, 1500, 0),
                item("Falafel pita", .entree, 1200, 1),
                item("Hummus + pita", .side, 600, 2),
                item("Lemonade", .drink, 350, 3)
            ]
        }
        if cuisine.contains("dessert") || cuisine.contains("donut") {
            return [
                item("Mini donuts", .dessert, 800, 0),
                item("Soft serve", .dessert, 600, 1),
                item("Coffee", .drink, 400, 2)
            ]
        }
        return [
            item("Chef's plate", .entree, 1400, 0, "Today's special — ask the window"),
            item("Side", .side, 600, 1),
            item("Drink", .drink, 350, 2)
        ]
    }
}

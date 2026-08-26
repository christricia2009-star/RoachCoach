import Foundation
import CoreLocation

/// Provides sample data so the app is fully browsable/demoable before a real
/// backend is wired up. Swap `APIService` calls to a real network layer
/// (see APIService.swift) once the FastAPI backend in /Backend is deployed.
final class MockDataService {
    static let shared = MockDataService()

    private init() {}

    // Sample coordinates around a generic downtown area (San Francisco).
    // Replace with real geocoded results once live data sources are connected.
    lazy var trucks: [Truck] = [
        Truck(name: "Bao Bao Bus", cuisineType: "Taiwanese", socialLinks: ["https://instagram.com/baobaobus"], averageConfidenceScore: 0.9, menuHighlights: ["Pork buns", "Milk tea"], rating: 4.8, averageWaitMinutes: 6),
        Truck(name: "El Fuego", cuisineType: "Mexican", socialLinks: ["https://instagram.com/elfuegotruck"], averageConfidenceScore: 0.8, menuHighlights: ["Al pastor tacos", "Elote"], rating: 4.6, averageWaitMinutes: 10),
        Truck(name: "Curry Up Now", cuisineType: "Indian Fusion", socialLinks: ["https://instagram.com/curryupnow"], averageConfidenceScore: 0.75, menuHighlights: ["Tikka masala burrito"], rating: 4.4, averageWaitMinutes: 12),
        Truck(name: "Waffle Wagon", cuisineType: "Breakfast", socialLinks: [], averageConfidenceScore: 0.6, menuHighlights: ["Liege waffles"], rating: 4.7, averageWaitMinutes: 7)
    ]

    lazy var sightings: [Sighting] = {
        guard trucks.count >= 4 else { return [] }
        let now = Date()
        var all = [
            Sighting(truckId: trucks[0].id, latitude: 37.7749, longitude: -122.4194, note: "Parked outside the office park", timestamp: now.addingTimeInterval(-10 * 60), confidenceLevel: .confirmed),
            Sighting(truckId: trucks[1].id, latitude: 37.7849, longitude: -122.4094, note: "Saw it near the plaza", timestamp: now.addingTimeInterval(-45 * 60), confidenceLevel: .likely),
            Sighting(truckId: trucks[2].id, latitude: 37.7649, longitude: -122.4294, note: "Posted their schedule this morning", timestamp: now.addingTimeInterval(-2 * 60 * 60), confidenceLevel: .scheduled),
            Sighting(truckId: trucks[3].id, latitude: 37.7729, longitude: -122.4014, note: "Confirmed by two people", timestamp: now.addingTimeInterval(-5 * 60), confidenceLevel: .confirmed)
        ]

        // Backfill ~14 days of historical sightings per truck so charts and
        // trend views have realistic-looking data to display out of the box.
        let levels: [ConfidenceLevel] = [.confirmed, .likely, .scheduled]
        for truck in trucks {
            for daysAgo in 1...14 {
                let count = Int.random(in: 1...3)
                for _ in 0..<count {
                    let level = levels.randomElement() ?? .likely
                    let timestamp = Calendar.current.date(byAdding: .day, value: -daysAgo, to: now) ?? now
                    all.append(
                        Sighting(
                            truckId: truck.id,
                            latitude: 37.77 + Double.random(in: -0.02...0.02),
                            longitude: -122.42 + Double.random(in: -0.02...0.02),
                            note: nil,
                            timestamp: timestamp,
                            confidenceLevel: level,
                            expiresAt: timestamp.addingTimeInterval(3 * 60 * 60)
                        )
                    )
                }
            }
        }
        return all
    }()

    func truck(for id: UUID) -> Truck? {
        trucks.first { $0.id == id }
    }

    func sightings(for truckId: UUID) -> [Sighting] {
        sightings.filter { $0.truckId == truckId }.sorted { $0.timestamp > $1.timestamp }
    }

    /// Simulates submitting a new crowdsourced sighting.
    func addSighting(_ sighting: Sighting) {
        sightings.append(sighting)
    }

    // MARK: - Menu (Phase 1: Menu + Order data models)

    lazy var menuItemsStore: [MenuItem] = {
        guard trucks.count >= 2 else { return [] }
        return [
            MenuItem(truckId: trucks[0].id.uuidString, name: "Pork Belly Bao", description: "Steamed bun, braised pork belly, pickled mustard greens", category: .entree, priceCents: 900, sortOrder: 0),
            MenuItem(truckId: trucks[0].id.uuidString, name: "Milk Tea", category: .drink, priceCents: 500, sortOrder: 1, modifiers: [MenuItemModifier(name: "Boba", priceDeltaCents: 75)]),
            MenuItem(truckId: trucks[0].id.uuidString, name: "Scallion Pancake", category: .side, priceCents: 400, sortOrder: 2),
            MenuItem(truckId: trucks[1].id.uuidString, name: "Al Pastor Tacos (3)", description: "Marinated pork, pineapple, cilantro, onion", category: .entree, priceCents: 1050, sortOrder: 0, modifiers: [MenuItemModifier(name: "Extra tortilla"), MenuItemModifier(name: "Extra spicy")]),
            MenuItem(truckId: trucks[1].id.uuidString, name: "Elote", category: .side, priceCents: 600, sortOrder: 1),
            MenuItem(truckId: trucks[1].id.uuidString, name: "Horchata", category: .drink, priceCents: 450, sortOrder: 2, isAvailable: false)
        ]
    }()

    func menuItems(for truckId: UUID) -> [MenuItem] {
        menuItemsStore
            .filter { $0.truckId == truckId.uuidString }
            .sorted { $0.sortOrder < $1.sortOrder }
    }

    func menuItem(id: String) -> MenuItem? {
        menuItemsStore.first { $0.id == id }
    }

    // MARK: - Orders (Phase 1: Menu + Order data models)

    lazy var ordersStore: [Order] = []

    func orders(for truckId: UUID) -> [Order] {
        ordersStore
            .filter { $0.truckId == truckId.uuidString }
            .sorted { $0.createdAt > $1.createdAt }
    }

    func order(id: String) -> Order? {
        ordersStore.first { $0.id == id }
    }

    /// Mirrors backend/main.py's create_order(): resolves prices from the
    /// current menu server-side rather than trusting the request payload.
    func createOrder(from request: NewOrderRequest) -> Order {
        let now = Date()
        var lineItems: [OrderLineItem] = []
        var subtotalCents = 0

        for line in request.items {
            guard let menuItem = menuItem(id: line.menuItemId) else { continue }
            let modifierDelta = line.modifiers.reduce(0) { $0 + $1.priceDeltaCents }
            let lineTotal = (menuItem.priceCents + modifierDelta) * line.quantity
            subtotalCents += lineTotal
            lineItems.append(
                OrderLineItem(
                    menuItemId: menuItem.id,
                    nameSnapshot: menuItem.name,
                    unitPriceCents: menuItem.priceCents,
                    quantity: line.quantity,
                    modifiers: line.modifiers,
                    lineTotalCents: lineTotal
                )
            )
        }

        let totalCents = subtotalCents + request.tipCents

        let order = Order(
            id: UUID().uuidString,
            truckId: request.truckId,
            customerUserId: request.customerUserId,
            customerName: request.customerName,
            status: .pending,
            items: lineItems,
            subtotalCents: subtotalCents,
            taxCents: 0,
            tipCents: request.tipCents,
            totalCents: totalCents,
            currency: "USD",
            specialInstructions: request.specialInstructions,
            pickupEtaMinutes: nil,
            paymentProvider: nil,
            paymentStatus: "unpaid",
            createdAt: now,
            updatedAt: now
        )

        ordersStore.append(order)
        return order
    }

    @discardableResult
    func updateOrderStatus(orderId: String, status: OrderStatus, pickupEtaMinutes: Int?) -> Order? {
        guard let index = ordersStore.firstIndex(where: { $0.id == orderId }) else { return nil }
        ordersStore[index].status = status
        if let pickupEtaMinutes {
            ordersStore[index].pickupEtaMinutes = pickupEtaMinutes
        }
        ordersStore[index].updatedAt = Date()
        return ordersStore[index]
    }

    /// Mock stand-in for a completed Square charge (Square is synchronous,
    /// unlike Stripe's create-intent-then-webhook flow) — see
    /// LiveAPIService.chargeSquare / backend/payments.py.
    func markOrderPaid(orderId: String, provider: String) -> Order? {
        guard let index = ordersStore.firstIndex(where: { $0.id == orderId }) else { return nil }
        ordersStore[index].paymentProvider = provider
        ordersStore[index].paymentStatus = "captured"
        ordersStore[index].updatedAt = Date()
        return ordersStore[index]
    }
}

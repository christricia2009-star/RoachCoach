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
}

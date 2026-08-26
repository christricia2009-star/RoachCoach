import SwiftUI
import CryptoKit

/// Deterministic truck ID generator — same algorithm as the Python side
/// (Backend/scheduler.py uses matching seeds to precompute these same
/// IDs for signal_fusion.py's KNOWN_TRUCK_NAMES). Using the same seed
/// string always produces the same UUID, so seeding is idempotent (safe
/// to run more than once — it recreates/updates the same records rather
/// than duplicating them) and the IDs are known ahead of time on both
/// sides without any manual copy-paste between app and backend.
func deterministicTruckID(from seed: String) -> UUID {
    let digest = SHA256.hash(data: Data(seed.utf8))
    let bytes = Array(digest.prefix(16))
    return UUID(uuid: (
        bytes[0], bytes[1], bytes[2], bytes[3],
        bytes[4], bytes[5], bytes[6], bytes[7],
        bytes[8], bytes[9], bytes[10], bytes[11],
        bytes[12], bytes[13], bytes[14], bytes[15]
    ))
}

/// The 14 confirmed real Sacramento/Plumas Lake-area trucks (see
/// scheduler.py for the matching Instagram handles used as seeds).
let realTruckSeeds: [(name: String, cuisine: String, seedHandle: String)] = [
    ("Drewski's Hot Rod Kitchen", "American/Comfort", "drewskis"),
    ("Buckhorn BBQ Truck", "BBQ", "thebuckhornbbqtruck"),
    ("SactoMoFo", "Food Truck Events", "sactomofo"),
    ("Krush Burger", "Burgers", "krushroseville"),
    ("Potato Patoto", "Loaded Tots", "the_potato_truck"),
    ("Alameda Tacos Food Truck", "Mexican", "alamedatacossac"),
    ("Mucho Nachos & Tacos", "Mexican", "muchonachossacramento"),
    ("The Pop Up Truck", "Grilled Cheese", "sactopopuptruck"),
    ("SanTacos", "Mexican", "santacosmx"),
    ("Tacoa Sacramento", "Mexican", "tacoasac"),
    ("Tacos GTO", "Mexican", "tacos_gto_"),
    ("Tacomiendo", "Mexican", "tacomiendofoodtruck"),
    ("Sac Tacos Foodtruck", "Mexican", "sactacosfoodtruck"),
    ("The Lumpia Truck", "Filipino", "thelumpiatruck"),
]

/// DEBUG/SETUP TOOL — not a permanent feature. Writes a couple of real
/// Truck + Sighting records straight into CloudKit using the exact same
/// CloudKitService code path the rest of the app already relies on. This
/// exists because "map shows no data" is ambiguous — it could mean
/// CloudKit is empty (expected, harmless) or CloudKit calls are silently
/// failing (a real bug the rest of the app currently hides via `try?`).
/// This view does NOT swallow errors — if something's wrong with your
/// CloudKit container/entitlement setup, you'll see the actual error text
/// here instead of just an empty screen.
struct DebugSeedDataView: View {
    @State private var statusMessages: [String] = []
    @State private var isSeeding = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("This writes all 14 confirmed real Sacramento/Plumas Lake trucks into CloudKit with FIXED, predictable IDs — same algorithm as the Python backend, so both sides already agree on every ID without you copying anything. Safe to tap more than once.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)

                    Button {
                        Task { await seedRealTrucks() }
                    } label: {
                        if isSeeding {
                            ProgressView()
                        } else {
                            Text("Seed 14 Real Trucks Into CloudKit")
                        }
                    }
                    .disabled(isSeeding)
                }

                Section {
                    Text("Quick single-truck round-trip test instead — useful if you just want to confirm CloudKit read/write works at all.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button("Seed 1 Test Truck") {
                        Task { await seedSingleTestTruck() }
                    }
                    .disabled(isSeeding)
                }

                if !statusMessages.isEmpty {
                    Section("Result — compare these IDs against what I gave you") {
                        ForEach(statusMessages, id: \.self) { message in
                            Text(message)
                                .font(.system(.footnote, design: .monospaced))
                                .foregroundStyle(message.hasPrefix("✅") ? .green : .red)
                                .textSelection(.enabled)
                        }
                    }
                }
            }
            .navigationTitle("Debug: Seed Data")
        }
    }

    private func seedRealTrucks() async {
        isSeeding = true
        statusMessages = []
        defer { isSeeding = false }

        for entry in realTruckSeeds {
            let seed = "roachcoachradar-truck-\(entry.seedHandle)"
            let truckId = deterministicTruckID(from: seed)

            let truck = Truck(
                id: truckId,
                name: entry.name,
                cuisineType: entry.cuisine,
                socialLinks: TruckSocialDirectory.seededURLStrings(forName: entry.name),
                averageConfidenceScore: 0.5,
                rating: 4.5,
                averageWaitMinutes: 8
            )

            do {
                try await CloudKitService.shared.createTruck(truck)
                statusMessages.append("✅ \(entry.name): \(truckId.uuidString)")
            } catch {
                statusMessages.append("❌ \(entry.name) FAILED: \(error.localizedDescription)")
            }
        }
    }

    private func seedSingleTestTruck() async {
        isSeeding = true
        statusMessages = []
        defer { isSeeding = false }

        let testTruck = Truck(
            name: "Debug Test Truck",
            cuisineType: "Test",
            averageConfidenceScore: 0.9,
            rating: 4.5,
            averageWaitMinutes: 5
        )

        do {
            try await CloudKitService.shared.createTruck(testTruck)
            statusMessages.append("✅ Created truck: \(testTruck.name)")
        } catch {
            statusMessages.append("❌ FAILED creating truck: \(error.localizedDescription)")
            statusMessages.append("   Full error: \(error)")
            return
        }

        let testSighting = Sighting(
            truckId: testTruck.id,
            latitude: 38.5816,
            longitude: -121.4944,
            note: "Debug seed sighting",
            confidenceLevel: .confirmed
        )

        do {
            try await CloudKitService.shared.submitSighting(testSighting)
            statusMessages.append("✅ Created sighting near \(testSighting.latitude), \(testSighting.longitude)")
        } catch {
            statusMessages.append("❌ FAILED creating sighting: \(error.localizedDescription)")
            return
        }

        do {
            let fetchedTrucks = try await CloudKitService.shared.fetchTrucks()
            statusMessages.append("✅ Read back \(fetchedTrucks.count) truck(s) from CloudKit")
        } catch {
            statusMessages.append("❌ FAILED reading trucks back: \(error.localizedDescription)")
        }
    }
}

#Preview {
    DebugSeedDataView()
}


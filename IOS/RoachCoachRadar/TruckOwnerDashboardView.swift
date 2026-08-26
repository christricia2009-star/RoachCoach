import SwiftUI

/// PHASE 2 FEATURE — scaffolded, not backend-connected.
///
/// Intent: let truck owners optionally claim their profile and
/// confirm/deny crowdsourced sightings about their own truck, without
/// requiring them to actively check in every day. This is opt-in and
/// lightweight by design — see Docs/README.md for rationale.
struct TruckOwnerDashboardView: View {
    @AppStorage("owner.claimedTruckId") private var claimedTruckId = ""
    @State private var trucks: [Truck] = []
    @State private var pendingSightings: [Sighting] = []
    @State private var showWiFiConsent = false
    @State private var showDebugSeed = false
    @State private var showWereHere = false
    @State private var statusMessage: String?
    @ObservedObject private var wifiService = WiFiDetectionService.shared
    @StateObject private var locationService = LocationService.shared
    private let api: APIServicing = CloudKitService.shared

    private var claimedTruck: Truck? {
        trucks.first { $0.id.uuidString == claimedTruckId }
    }

    var body: some View {
        NavigationStack {
            List {
                if claimedTruck == nil {
                    Section("Claim your truck") {
                        Text("Pick your truck, then tap We’re here now to drop a confirmed pin at your GPS. Customers see it immediately.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Picker("My truck", selection: $claimedTruckId) {
                            Text("Select…").tag("")
                            ForEach(trucks) { truck in
                                Text(truck.name).tag(truck.id.uuidString)
                            }
                        }
                    }
                } else if let truck = claimedTruck {
                    Section("Live pin") {
                        Text(truck.name).font(.headline)
                        Button("We're here now") {
                            showWereHere = true
                        }
                        .disabled(locationService.currentLocation == nil)
                        if let statusMessage {
                            Text(statusMessage).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    Section("Pending customer reports") {
                        if pendingSightings.isEmpty {
                            Text("No pending sightings to review.")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(pendingSightings) { sighting in
                                Text(sighting.note ?? "Sighting reported")
                            }
                        }
                    }
                }

                Section("Detection Settings") {
                    HStack {
                        Label("Wi-Fi Truck Detection", systemImage: "wifi")
                        Spacer()
                        Text(wifiService.hasUserConsented ? "On" : "Off")
                            .foregroundStyle(.secondary)
                    }
                    Button(wifiService.hasUserConsented ? "Review Notice" : "Turn On…") {
                        showWiFiConsent = true
                    }
                }

                Section("Debug / Setup") {
                    Text("Map showing no data? Use this to confirm CloudKit reads/writes are actually working.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button("Seed Test Data Into CloudKit") {
                        showDebugSeed = true
                    }
                }
            }
            .navigationTitle("Owner Dashboard")
            .task {
                locationService.requestPermission()
                trucks = (try? await api.fetchTrucks()) ?? []
                if let truck = claimedTruck {
                    pendingSightings = (try? await api.fetchSightings(forTruck: truck.id)) ?? []
                }
            }
            .sheet(isPresented: $showWiFiConsent) {
                WiFiConsentView()
            }
            .sheet(isPresented: $showDebugSeed) {
                DebugSeedDataView()
            }
            .sheet(isPresented: $showWereHere) {
                QuickCheckInView(trucks: claimedTruck.map { [$0] } ?? trucks, isOwner: true) { sighting in
                    Task {
                        try? await api.submitSighting(sighting)
                        statusMessage = "Live pin dropped. Customers can see you now."
                        pendingSightings = (try? await api.fetchSightings(forTruck: sighting.truckId)) ?? []
                    }
                }
            }
        }
    }
}

#Preview {
    TruckOwnerDashboardView()
}

import SwiftUI

/// PHASE 2 FEATURE — scaffolded, not backend-connected.
///
/// Intent: let truck owners optionally claim their profile and
/// confirm/deny crowdsourced sightings about their own truck, without
/// requiring them to actively check in every day. This is opt-in and
/// lightweight by design — see Docs/README.md for rationale.
struct TruckOwnerDashboardView: View {
    @State private var isClaimed = false
    @State private var pendingSightings: [Sighting] = []
    @State private var showWiFiConsent = false
    @State private var showDebugSeed = false
    @ObservedObject private var wifiService = WiFiDetectionService.shared

    var body: some View {
        NavigationStack {
            List {
                if !isClaimed {
                    Section {
                        Text("Own a food truck? Claim your profile to confirm or deny sightings reported about you, and see how customers find you.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Button("Claim My Truck") {
                            // TODO: wire to POST /trucks/{id}/claim once
                            // backend auth (e.g. Sign in with Apple + a
                            // verification step) is implemented.
                            isClaimed = true
                        }
                    }
                } else {
                    Section("Pending Sighting Confirmations") {
                        if pendingSightings.isEmpty {
                            Text("No pending sightings to review.")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(pendingSightings) { sighting in
                                HStack {
                                    Text(sighting.note ?? "Sighting reported")
                                    Spacer()
                                    Button("Confirm") { }
                                        .buttonStyle(.borderedProminent)
                                    Button("Deny") { }
                                        .buttonStyle(.bordered)
                                }
                            }
                        }
                    }

                    Section("Insights") {
                        Text("Coming soon: how many people viewed your profile, favorited your truck, and reported sightings this week.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
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
            .sheet(isPresented: $showWiFiConsent) {
                WiFiConsentView()
            }
            .sheet(isPresented: $showDebugSeed) {
                DebugSeedDataView()
            }
        }
    }
}

#Preview {
    TruckOwnerDashboardView()
}

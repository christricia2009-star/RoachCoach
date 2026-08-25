import SwiftUI

struct RootTabView: View {
    @State private var showIntelligence = false
    @State private var showWatchZones = false
    @State private var showWarRoom = false
    @State private var showSettings = false

    var body: some View {
        TabView {
            TrucksListView()
                .tabItem { Label("Trucks", systemImage: "truck.box.fill") }

            MapContentView()
                .tabItem { Label("Radar", systemImage: "dot.radiowaves.left.and.right") }

            FavoritesView()
                .tabItem { Label("Watchlist", systemImage: "heart.fill") }

            PredictiveScheduleView()
                .tabItem { Label("Predictions", systemImage: "chart.line.uptrend.xyaxis") }

            TruckOwnerDashboardView()
                .tabItem { Label("Owner", systemImage: "steeringwheel") }

            NavigationStack {
                List {
                    Button { showIntelligence = true } label: { Label("Radar Intelligence", systemImage: "brain.head.profile") }
                    Button { showWatchZones = true } label: { Label("Watch Zones", systemImage: "location.viewfinder") }
                    Button { showWarRoom = true } label: { Label("AI Radar War Room", systemImage: "brain.head.profile") }
                    Button { showSettings = true } label: { Label("API & Radar Settings", systemImage: "key.fill") }
                    NavigationLink { RadarLabView() } label: { Label("Radar Lab", systemImage: "flask") }
                    HStack { Label("Scout Level", systemImage: "shield.fill"); Spacer(); Text(ReputationService.shared.reputation.title).foregroundStyle(.secondary) }
                }.navigationTitle("More Radar")
            }
            .tabItem { Label("More", systemImage: "ellipsis.circle") }
        }
        .task {
            NotificationService.shared.requestPermission()
            await CloudKitService.shared.installRadarSubscription()
            GeofenceRadarService.shared.requestPermission()
        }
        .sheet(isPresented: $showIntelligence) {
            // Intelligence uses the current CloudKit-backed dataset from the radar tab on demand.
            RadarIntelligenceView()
        }
        .sheet(isPresented: $showWatchZones) {
            WatchZoneView()
        }
        .sheet(isPresented: $showWarRoom) {
            RadarWarRoomView()
        }
        .sheet(isPresented: $showSettings) {
            NavigationStack { APISettingsView() }
        }
    }
}

#Preview { RootTabView() }

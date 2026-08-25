import SwiftUI

struct FavoritesView: View {
    @State private var allTrucks: [Truck] = []
    @State private var sightings: [Sighting] = []
    @StateObject private var favorites = FavoritesStore.shared
    @StateObject private var locationService = LocationService.shared
    private let api: APIServicing = CloudKitService.shared

    var body: some View {
        NavigationStack {
            List {
                if favoriteTrucks.isEmpty {
                    ContentUnavailableView(
                        "No Favorites Yet",
                        systemImage: "heart",
                        description: Text("Tap the heart on a truck profile to build your personal radar watchlist.")
                    )
                } else {
                    ForEach(favoriteTrucks) { truck in
                        NavigationLink { TruckProfileView(truck: truck) } label: {
                            HStack(spacing: 12) {
                                Image(systemName: "heart.fill").foregroundStyle(.pink)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(truck.name).fontWeight(.semibold)
                                    Text(truck.cuisineType).font(.caption).foregroundStyle(.secondary)
                                    if let latest = latestSighting(for: truck) {
                                        Text("Last seen \(latest.timestamp, style: .relative)")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    } else {
                                        Text("No live pin yet")
                                            .font(.caption2)
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                                Spacer()
                                if let latest = latestSighting(for: truck) {
                                    Button {
                                        MapsLauncher.directions(to: latest.coordinate, name: truck.name)
                                    } label: {
                                        Image(systemName: "arrow.triangle.turn.up.right.diamond.fill")
                                    }
                                    .buttonStyle(.borderless)
                                }
                            }
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) { favorites.toggle(truck.id) } label: { Label("Unfollow", systemImage: "heart.slash") }
                        }
                    }
                }
            }
            .navigationTitle("Radar Watchlist")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Text("\(favoriteTrucks.count) watched").font(.caption).foregroundStyle(.secondary) } }
            .task {
                locationService.requestPermission()
                async let loadedTrucks = api.fetchTrucks()
                async let loadedSightings = api.fetchSightings()
                allTrucks = (try? await loadedTrucks) ?? []
                sightings = (try? await loadedSightings) ?? []
            }
        }
    }

    private var favoriteTrucks: [Truck] { allTrucks.filter { favorites.contains($0.id) } }

    private func latestSighting(for truck: Truck) -> Sighting? {
        sightings
            .filter { $0.truckId == truck.id && !$0.isExpired }
            .sorted { $0.timestamp > $1.timestamp }
            .first
    }
}

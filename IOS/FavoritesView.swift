import SwiftUI

struct FavoritesView: View {
    @State private var allTrucks: [Truck] = []
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
                                VStack(alignment: .leading) {
                                    Text(truck.name).fontWeight(.semibold)
                                    Text(truck.cuisineType).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text("WATCHING").font(.caption2.bold().monospaced()).foregroundStyle(.green)
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
                allTrucks = (try? await api.fetchTrucks()) ?? []
            }
        }
    }

    private var favoriteTrucks: [Truck] { allTrucks.filter { favorites.contains($0.id) } }
}

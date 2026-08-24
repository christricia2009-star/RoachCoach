import SwiftUI
import CoreLocation

/// A real, browsable list of every truck in the system — not just map pins.
/// This is the "I just want to see what's out there" screen. Sorted nearest
/// first when we have a location fix, otherwise alphabetically.
struct TrucksListView: View {
    @State private var trucks: [Truck] = []
    @State private var sightings: [Sighting] = []
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var selectedCuisine: String?
    @State private var selectedTruck: Truck?
    @StateObject private var locationService = LocationService.shared
    @StateObject private var favorites = FavoritesStore.shared
    private let api: APIServicing = CloudKitService.shared

    private var cuisines: [String] {
        Array(Set(trucks.map(\.cuisineType))).sorted()
    }

    private var filtered: [Truck] {
        trucks.filter { truck in
            let matchesSearch = searchText.isEmpty
                || truck.name.localizedCaseInsensitiveContains(searchText)
                || truck.cuisineType.localizedCaseInsensitiveContains(searchText)
            let matchesCuisine = selectedCuisine == nil || truck.cuisineType == selectedCuisine
            return matchesSearch && matchesCuisine
        }
    }

    private var sorted: [Truck] {
        guard let location = locationService.currentLocation else {
            return filtered.sorted { $0.name.localizedCompare($1.name) == .orderedAscending }
        }
        // Trucks don't carry their own coordinate — we rank by the nearest
        // active sighting for that truck, falling back to alphabetical for
        // trucks with no current sighting at all.
        return filtered.sorted { a, b in
            let distA = nearestDistance(for: a, from: location)
            let distB = nearestDistance(for: b, from: location)
            switch (distA, distB) {
            case let (.some(x), .some(y)): return x < y
            case (.some, .none): return true
            case (.none, .some): return false
            default: return a.name.localizedCompare(b.name) == .orderedAscending
            }
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading && trucks.isEmpty {
                    ProgressView("Loading trucks…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if trucks.isEmpty {
                    emptyState
                } else {
                    List {
                        if !activeSection.isEmpty {
                            Section("Spotted Recently") {
                                ForEach(activeSection) { truck in
                                    truckRow(truck)
                                }
                            }
                        }
                        Section(activeSection.isEmpty ? "All Trucks" : "All Trucks") {
                            ForEach(sorted.filter { !activeTruckIDs.contains($0.id) }) { truck in
                                truckRow(truck)
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .searchable(text: $searchText, prompt: "Search trucks, cuisine…")
            .navigationTitle("Trucks")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("All Cuisines") { selectedCuisine = nil }
                        ForEach(cuisines, id: \.self) { cuisine in
                            Button(cuisine) { selectedCuisine = cuisine }
                        }
                    } label: {
                        Label("Filter", systemImage: selectedCuisine == nil ? "line.3.horizontal.decrease.circle" : "line.3.horizontal.decrease.circle.fill")
                    }
                }
            }
            .refreshable { await loadData() }
            .task { await loadData() }
            .sheet(item: $selectedTruck) { truck in
                TruckProfileView(truck: truck)
            }
        }
    }

    // MARK: - Rows

    private var activeTruckIDs: Set<UUID> {
        Set(sightings.filter { !$0.isExpired }.map(\.truckId))
    }

    private var activeSection: [Truck] {
        sorted.filter { activeTruckIDs.contains($0.id) }
    }

    private func truckRow(_ truck: Truck) -> some View {
        Button {
            selectedTruck = truck
        } label: {
            HStack(spacing: 12) {
                truckThumbnail(truck)

                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(truck.name)
                            .font(.body.weight(.semibold))
                            .foregroundStyle(.primary)
                        if activeTruckIDs.contains(truck.id) {
                            Circle().fill(.green).frame(width: 7, height: 7)
                        }
                    }
                    Text(truck.cuisineType)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 10) {
                        Label(String(format: "%.1f", truck.rating), systemImage: "star.fill")
                            .foregroundStyle(.orange)
                        if let distance = distanceLabel(for: truck) {
                            Label(distance, systemImage: "location.fill")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .font(.caption)
                }

                Spacer()

                if favorites.contains(truck.id) {
                    Image(systemName: "heart.fill").foregroundStyle(.red)
                }
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
    }

    private func truckThumbnail(_ truck: Truck) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.orange.opacity(0.15))
            Image(systemName: "truck.box.fill")
                .font(.title3)
                .foregroundStyle(.orange)
        }
        .frame(width: 48, height: 48)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "truck.box")
                .font(.system(size: 42))
                .foregroundStyle(.secondary)
            Text("No trucks yet")
                .font(.headline)
            Text("Once trucks are added to the directory, they'll show up here.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Helpers

    private func nearestDistance(for truck: Truck, from location: CLLocation) -> CLLocationDistance? {
        let truckSightings = sightings.filter { $0.truckId == truck.id && !$0.isExpired }
        guard !truckSightings.isEmpty else { return nil }
        return truckSightings
            .compactMap { locationService.distance(to: $0.coordinate) }
            .min()
    }

    private func distanceLabel(for truck: Truck) -> String? {
        guard let location = locationService.currentLocation else { return nil }
        guard let sighting = sightings
            .filter({ $0.truckId == truck.id && !$0.isExpired })
            .min(by: { (locationService.distance(to: $0.coordinate) ?? .infinity) < (locationService.distance(to: $1.coordinate) ?? .infinity) })
        else { return nil }
        _ = location
        return locationService.formattedDistance(to: sighting.coordinate)
    }

    private func loadData() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let t = api.fetchTrucks()
            async let s = api.fetchSightings()
            trucks = try await t
            sightings = try await s
        } catch {
            print("TrucksListView load failed: \(error)")
        }
    }
}

#Preview { TrucksListView() }

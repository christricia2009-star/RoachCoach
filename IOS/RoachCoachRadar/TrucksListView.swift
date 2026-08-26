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
    @State private var selectedRegion: String?
    @State private var selectedTruck: Truck?
    @StateObject private var locationService = LocationService.shared
    @StateObject private var favorites = FavoritesStore.shared
    private let api: APIServicing = CloudKitService.shared

    private var listedTrucks: [Truck] {
        trucks.filter(\.hasSocialPresence)
    }

    private var cuisines: [String] {
        Array(Set(listedTrucks.map(\.cuisineType).filter { !$0.isEmpty })).sorted()
    }

    private var regions: [String] {
        let present = Set(listedTrucks.map(\.region))
        return TruckSocialDirectory.regionOrder.filter { present.contains($0) }
            + present.subtracting(TruckSocialDirectory.regionOrder).sorted()
    }

    private var filtered: [Truck] {
        listedTrucks.filter { truck in
            let matchesSearch = searchText.isEmpty
                || truck.name.localizedCaseInsensitiveContains(searchText)
                || truck.cuisineType.localizedCaseInsensitiveContains(searchText)
                || truck.region.localizedCaseInsensitiveContains(searchText)
            let matchesCuisine = selectedCuisine == nil || truck.cuisineType == selectedCuisine
            let matchesRegion = selectedRegion == nil || truck.region == selectedRegion
            return matchesSearch && matchesCuisine && matchesRegion
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
                } else if listedTrucks.isEmpty {
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
                        ForEach(regionSections, id: \.region) { section in
                            Section(section.region) {
                                ForEach(section.trucks) { truck in
                                    truckRow(truck)
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .searchable(text: $searchText, prompt: "Search trucks, cuisine, region…")
            .navigationTitle("Trucks")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("All Regions") { selectedRegion = nil }
                        ForEach(regions, id: \.self) { region in
                            Button(region) { selectedRegion = region }
                        }
                        Divider()
                        Button("All Cuisines") { selectedCuisine = nil }
                        ForEach(cuisines, id: \.self) { cuisine in
                            Button(cuisine) { selectedCuisine = cuisine }
                        }
                    } label: {
                        Label(
                            "Filter",
                            systemImage: (selectedCuisine == nil && selectedRegion == nil)
                                ? "line.3.horizontal.decrease.circle"
                                : "line.3.horizontal.decrease.circle.fill"
                        )
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
                    Text([truck.cuisineType, truck.region].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text(TruckHoursDirectory.status(for: truck).badge)
                        .font(.caption2.bold())
                        .foregroundStyle(TruckHoursDirectory.status(for: truck).isOpen == true ? .green : .secondary)
                    HStack(spacing: 10) {
                        if let distance = distanceLabel(for: truck) {
                            Label(distance, systemImage: "location.fill")
                                .foregroundStyle(.secondary)
                        }
                        if let seen = lastSeenLabel(for: truck) {
                            Label(seen, systemImage: "clock")
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
        TruckAvatar(truck: truck, size: 48)
    }

    private var regionSections: [(region: String, trucks: [Truck])] {
        let remaining = sorted.filter { !activeTruckIDs.contains($0.id) }
        let grouped = Dictionary(grouping: remaining, by: \.region)
        var order = TruckSocialDirectory.regionOrder
        for key in grouped.keys.sorted() {
            let region = key.isEmpty ? "Other" : key
            if !order.contains(region) {
                order.append(region)
            }
        }
        return order.compactMap { region in
            let items = grouped[region] ?? (region == "Other" ? grouped[""] : nil) ?? []
            guard !items.isEmpty else { return nil }
            return (region, items)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "truck.box")
                .font(.system(size: 42))
                .foregroundStyle(.secondary)
            Text(trucks.isEmpty ? "No trucks yet" : "No Instagram/Facebook trucks")
                .font(.headline)
            Text(
                trucks.isEmpty
                    ? "Once trucks are added to the directory, they'll show up here."
                    : "Trucks without Instagram or Facebook stay hidden — those pages are how we get timely location updates."
            )
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

    private func lastSeenLabel(for truck: Truck) -> String? {
        guard let latest = sightings
            .filter({ $0.truckId == truck.id && !$0.isExpired })
            .max(by: { $0.timestamp < $1.timestamp })
        else { return nil }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: latest.timestamp, relativeTo: Date())
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

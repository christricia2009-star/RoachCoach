import SwiftUI
import UIKit

struct TruckProfileView: View {
    let truck: Truck

    @State private var recentSightings: [Sighting] = []
    @StateObject private var favorites = FavoritesStore.shared
    @StateObject private var locationService = LocationService.shared
    private let api: APIServicing = CloudKitService.shared

    private var socialLinks: [TruckSocialLink] {
        TruckSocialDirectory.links(for: truck)
    }

    private var latestSighting: Sighting? {
        recentSightings.first { !$0.isExpired } ?? recentSightings.first
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(truck.name)
                            .font(.title2)
                            .fontWeight(.bold)
                        Text(truck.cuisineType)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)

                        HStack(spacing: 16) {
                            Label("\(String(format: "%.1f", truck.rating))", systemImage: "star.fill")
                                .foregroundStyle(.yellow)
                            Label("~\(truck.averageWaitMinutes) min wait", systemImage: "clock")
                                .foregroundStyle(.secondary)
                        }
                        .font(.footnote)

                        HStack {
                            Image(systemName: "checkmark.seal.fill")
                                .foregroundStyle(.green)
                            Text("\(Int(truck.averageConfidenceScore * 100))% reliability score")
                                .font(.footnote)
                        }

                        if let latest = latestSighting {
                            VStack(alignment: .leading, spacing: 4) {
                                Label("Last seen \(latest.timestamp, style: .relative)", systemImage: "clock")
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                if let distanceText = locationService.formattedDistance(to: latest.coordinate),
                                   let eta = locationService.estimatedWalkingMinutes(to: latest.coordinate) {
                                    Label("\(distanceText) · ~\(eta) min walk", systemImage: "location.fill")
                                        .font(.footnote)
                                        .foregroundStyle(.blue)
                                }
                            }
                        } else {
                            Text("No live pin yet — check Instagram or scan radar.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if let latest = latestSighting {
                    Section {
                        Button {
                            MapsLauncher.directions(to: latest.coordinate, name: truck.name)
                        } label: {
                            Label("Get directions", systemImage: "arrow.triangle.turn.up.right.diamond.fill")
                        }
                        ShareLink(
                            item: "\(truck.name) last seen near \(latest.latitude), \(latest.longitude)"
                        ) {
                            Label("Share this pin", systemImage: "square.and.arrow.up")
                        }
                    }
                }

                if !truck.menuHighlights.isEmpty {
                    Section("Menu Highlights") {
                        ForEach(truck.menuHighlights, id: \.self) { item in
                            Text(item)
                        }
                    }
                }

                Section {
                    TruckReliabilityChartView(sightings: recentSightings)
                }

                Section("Recent Sightings") {
                    if recentSightings.isEmpty {
                        Text("No recent sightings reported yet.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(recentSightings.prefix(10)) { sighting in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(sighting.confidenceLevel.rawValue)
                                        .font(.caption)
                                        .fontWeight(.semibold)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 2)
                                        .background(badgeColor(for: sighting.confidenceLevel).opacity(0.2))
                                        .foregroundStyle(badgeColor(for: sighting.confidenceLevel))
                                        .clipShape(Capsule())
                                    Spacer()
                                    Text(sighting.timestamp, style: .relative)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                if let note = sighting.note {
                                    Text(note)
                                        .font(.body)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }

                if !socialLinks.isEmpty {
                    Section("Social") {
                        ForEach(socialLinks) { link in
                            Link(destination: link.url) {
                                Label {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(link.title)
                                            .foregroundStyle(.primary)
                                        Text(link.handle)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                } icon: {
                                    Image(systemName: link.systemImage)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Truck Details")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        toggleFavorite()
                    } label: {
                        Image(systemName: favorites.contains(truck.id) ? "heart.fill" : "heart")
                    }
                }
            }
            .task {
                recentSightings = (try? await api.fetchSightings(forTruck: truck.id)) ?? []
                locationService.requestPermission()
            }
        }
    }

    private func toggleFavorite() {
        favorites.toggle(truck.id)

        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.success)

        if favorites.contains(truck.id) {
            // Demonstrates the real local-notification pipeline: favoriting
            // a truck schedules a genuine on-device alert a few seconds
            // later, simulating "this truck was just spotted." Once a live
            // backend exists, replace this trigger with a background fetch
            // or silent push that fires only on an actual new confirmed
            // sighting for a followed truck.
            NotificationService.shared.scheduleTruckSpottedNotification(
                truckName: truck.name,
                note: "You'll get alerts like this when \(truck.name) is spotted nearby.",
                delaySeconds: 4
            )
        }
    }

    private func badgeColor(for level: ConfidenceLevel) -> Color {
        switch level {
        case .confirmed: return .green
        case .likely: return .orange
        case .scheduled: return .gray
        }
    }
}

#Preview {
    TruckProfileView(truck: MockDataService.shared.trucks[0])
}

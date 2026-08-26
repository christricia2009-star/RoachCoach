import SwiftUI
import UIKit
import CoreLocation

struct TruckProfileView: View {
    let truck: Truck

    @State private var recentSightings: [Sighting] = []
    @State private var showCaptionImport = false
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
                        HStack(alignment: .top, spacing: 14) {
                            TruckAvatar(truck: truck, size: 72)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(truck.name)
                                    .font(.title2)
                                    .fontWeight(.bold)
                                Text(truck.cuisineType)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                if !truck.region.isEmpty {
                                    Text(truck.region)
                                        .font(.caption.bold())
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 3)
                                        .background(Color.orange.opacity(0.16))
                                        .foregroundStyle(.orange)
                                        .clipShape(Capsule())
                                }
                            }
                        }

                        let hours = TruckHoursDirectory.status(for: truck)
                        HStack(spacing: 8) {
                            Text(hours.badge)
                                .font(.caption.bold())
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background((hours.isOpen == true ? Color.green : hours.isOpen == false ? Color.red : Color.orange).opacity(0.18))
                                .foregroundStyle(hours.isOpen == true ? .green : hours.isOpen == false ? .red : .orange)
                                .clipShape(Capsule())
                            Text(hours.summary)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

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
                    Button {
                        showCaptionImport = true
                    } label: {
                        Label("Paste Instagram caption", systemImage: "doc.on.clipboard")
                    }
                    if recentSightings.isEmpty {
                        Text("No CloudKit sightings for this truck in the last 14 days yet. Map pins from a radar scan can appear before they land in this list.")
                            .font(.footnote)
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
            .sheet(isPresented: $showCaptionImport) {
                CaptionPinImportView(truck: truck) { sighting in
                    Task {
                        try? await api.submitSighting(sighting)
                        recentSightings = (try? await api.fetchSightings(forTruck: truck.id)) ?? []
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

struct CaptionPinImportView: View {
    let truck: Truck
    var onSubmit: (Sighting) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var caption = ""
    @State private var parsedQuery = ""
    @State private var status = "Copy the Instagram caption, then tap Paste."
    @State private var isWorking = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Caption") {
                    TextEditor(text: $caption)
                        .frame(minHeight: 140)
                    Button("Paste from clipboard") {
                        caption = UIPasteboard.general.string ?? caption
                        parsedQuery = Self.locationQuery(from: caption) ?? ""
                    }
                }
                Section("Parsed location") {
                    Text(parsedQuery.isEmpty ? "No street / park line found yet." : parsedQuery)
                        .foregroundStyle(parsedQuery.isEmpty ? .secondary : .primary)
                }
                Section {
                    Button("Drop pin on radar") {
                        Task { await dropPin() }
                    }
                    .disabled(caption.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isWorking)
                }
                Section {
                    Text(status)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Import caption")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .onChange(of: caption) { _, newValue in
                parsedQuery = Self.locationQuery(from: newValue) ?? ""
            }
        }
    }

    private func dropPin() async {
        isWorking = true
        defer { isWorking = false }
        let query = Self.locationQuery(from: caption) ?? caption
        parsedQuery = query
        status = "Geocoding \(query)…"
        let geocoder = CLGeocoder()
        do {
            let marks = try await geocoder.geocodeAddressString(query + ", California")
            let inRegion = marks.first { mark in
                guard let loc = mark.location else { return false }
                return (38.0...40.2).contains(loc.coordinate.latitude)
                    && (-122.8...(-120.2)).contains(loc.coordinate.longitude)
            } ?? marks.first
            guard let loc = inRegion?.location else {
                status = "Could not geocode that caption."
                return
            }
            let sighting = Sighting(
                truckId: truck.id,
                latitude: loc.coordinate.latitude,
                longitude: loc.coordinate.longitude,
                note: caption.trimmingCharacters(in: .whitespacesAndNewlines),
                confidenceLevel: .likely
            )
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            onSubmit(sighting)
            dismiss()
        } catch {
            status = "Geocode failed: \(error.localizedDescription)"
        }
    }

    static func locationQuery(from caption: String) -> String? {
        let lines = caption
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && $0.lowercased() != "menu:" }

        let street = try? NSRegularExpression(
            pattern: #"\d{3,5}\s+.+(Ave|Avenue|Blvd|St|Street|Dr|Drive|Rd|Road|Way|Ln|Lane|Pkwy|Park|Parking)"#,
            options: [.caseInsensitive]
        )
        for line in lines.reversed() {
            let range = NSRange(line.startIndex..., in: line)
            if street?.firstMatch(in: line, range: range) != nil {
                return line
            }
        }
        let placeHints = ["parking", "park", "plaza", "brewery", "school", "bx ", "afb"]
        if let line = lines.last(where: { candidate in
            placeHints.contains { candidate.lowercased().contains($0) }
        }) {
            return line
        }
        return lines.last
    }
}

#Preview {
    TruckProfileView(truck: MockDataService.shared.trucks[0])
}

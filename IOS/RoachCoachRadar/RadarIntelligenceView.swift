import SwiftUI
import CoreLocation

struct RadarIntelligenceView: View {
    @State private var trucks: [Truck] = []
    @State private var sightings: [Sighting] = []
    @Environment(\.dismiss) private var dismiss
    @State private var selectedRange = 24

    private var reputation: RadarReputation { ReputationService.shared.reputation }

    var body: some View {
        NavigationStack {
            List {
                Section("Prediction Engine") {
                    Text("The radar learns from historical sightings on this device. It estimates the next likely zone and time window without requiring a server-side model.").font(.footnote).foregroundStyle(.secondary)
                    ForEach(trucks.prefix(10)) { truck in
                        if let prediction = PredictionEngine.shared.predictions(for: truck, sightings: sightings).first {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack { Text(truck.name).bold(); Spacer(); Text("\(prediction.confidence)%").foregroundStyle(.green).bold() }
                                Text("Likely around \(prediction.predictedCoordinate.latitude, specifier: "%.4f"), \(prediction.predictedCoordinate.longitude, specifier: "%.4f")")
                                    .font(.caption).foregroundStyle(.secondary)
                                Text("\(prediction.windowStart, style: .time)–\(prediction.windowEnd, style: .time) • \(prediction.sampleCount) samples")
                                    .font(.caption)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
                Section("Scout Reputation") {
                    HStack { Image(systemName: "shield.lefthalf.filled"); VStack(alignment: .leading) { Text(reputation.title).bold(); Text("Level \(reputation.level) • \(reputation.xp) XP").font(.caption).foregroundStyle(.secondary) }; Spacer(); Text("\(reputation.accuracy)%").bold() }
                    if !reputation.badges.isEmpty { Text(reputation.badges.joined(separator: " • ")).font(.caption) }
                }
                Section("Heatmap Window") {
                    Picker("Window", selection: $selectedRange) {
                        Text("1 hour").tag(1); Text("3 hours").tag(3); Text("24 hours").tag(24); Text("7 days").tag(168); Text("All").tag(99999)
                    }.pickerStyle(.menu)
                    HeatmapSummaryView(sightings: sightings, hours: selectedRange)
                }
            }
            .navigationTitle("Radar Intelligence")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task {
                async let t = CloudKitService.shared.fetchTrucks()
                async let s = CloudKitService.shared.fetchSightings()
                trucks = (try? await t) ?? []
                sightings = (try? await s) ?? []
            }
        }
    }
}

private struct HeatmapSummaryView: View {
    let sightings: [Sighting]
    let hours: Int
    var body: some View {
        let cutoff = hours == 99999 ? .distantPast : Date().addingTimeInterval(-Double(hours) * 3600)
        let active = sightings.filter { $0.timestamp >= cutoff && !$0.isExpired }
        let clusters = RadarEngine.shared.buildHotspots(from: active).sorted { $0.intensity > $1.intensity }
        VStack(alignment: .leading, spacing: 8) {
            Text("\(active.count) reports • \(clusters.count) active hotspots").bold()
            ForEach(Array(clusters.prefix(5))) { hotspot in
                HStack { Image(systemName: "flame.fill").foregroundStyle(.orange); Text("\(hotspot.count) contacts"); Spacer(); Text("\(Int(hotspot.intensity * 100))% intensity").font(.caption).foregroundStyle(.secondary) }
            }
        }.padding(.vertical, 4)
    }
}

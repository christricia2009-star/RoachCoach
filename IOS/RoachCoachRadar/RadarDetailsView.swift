import SwiftUI
import CoreLocation

struct RadarDetailsView: View {
    let trucks: [Truck]
    let sightings: [Sighting]
    let location: CLLocation?
    @Environment(\.dismiss) private var dismiss

    private var stats: RadarStats { RadarEngine.shared.stats(sightings: sightings, location: location) }

    var body: some View {
        NavigationStack {
            List {
                Section("Right now") {
                    StatusRow(title: "GPS", value: location == nil ? "Waiting" : "On", icon: "location.fill", tint: location == nil ? .orange : .green)
                    StatusRow(title: "Active pins", value: "\(stats.activeSightings)", icon: "mappin.and.ellipse", tint: .orange)
                    StatusRow(title: "Confirmed", value: "\(stats.confirmedSightings)", icon: "checkmark.seal.fill", tint: .green)
                }
                Section("Closest trucks") {
                    let nearest = sightings.filter { !$0.isExpired }.compactMap { sighting -> (Sighting, Double)? in
                        guard let location else { return nil }
                        let d = location.distance(from: CLLocation(latitude: sighting.latitude, longitude: sighting.longitude)) / 1609.34
                        return (sighting, d)
                    }.sorted { $0.1 < $1.1 }.prefix(12)
                    if nearest.isEmpty {
                        Text("No live pins near you yet. Pull to refresh on Radar or tap Scan.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(Array(nearest), id: \.0.id) { item in
                        let truck = trucks.first(where: { $0.id == item.0.truckId })
                        let name = truck?.name ?? item.0.note ?? "Listing"
                        HStack {
                            Image(systemName: "mappin.circle.fill")
                                .foregroundStyle(item.0.confidenceLevel == .confirmed ? .green : .orange)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(name).fontWeight(.semibold)
                                Text("\(item.1 < 0.1 ? "Very close" : String(format: "%.1f mi", item.1)) · \(item.0.timestamp, style: .relative)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button {
                                MapsLauncher.directions(to: item.0.coordinate, name: name)
                            } label: {
                                Image(systemName: "arrow.triangle.turn.up.right.diamond.fill")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
            .navigationTitle("Nearby")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}

private struct StatusRow: View {
    let title: String; let value: String; let icon: String; let tint: Color
    var body: some View { HStack { Image(systemName: icon).foregroundStyle(tint).frame(width: 24); Text(title); Spacer(); Text(value).font(.caption.bold().monospaced()).foregroundStyle(tint) } }
}

private struct ThreatGauge: View {
    let score: Int
    var body: some View {
        VStack(spacing: 12) {
            Gauge(value: Double(score), in: 0...100) { Text("Radar Confidence") } currentValueLabel: { Text("\(score)%") }
                .gaugeStyle(.accessoryCircularCapacity)
                .tint(.orange)
                .scaleEffect(1.7)
                .frame(height: 110)
            Text(score >= 75 ? "HIGH ACTIVITY" : score >= 45 ? "ELEVATED ACTIVITY" : "LOW ACTIVITY")
                .font(.headline.monospaced()).foregroundStyle(score >= 75 ? .red : score >= 45 ? .orange : .green)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 18)
    }
}

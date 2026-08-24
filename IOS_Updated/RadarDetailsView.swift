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
                Section("Mission Status") {
                    StatusRow(title: "Radar", value: "ONLINE", icon: "dot.radiowaves.left.and.right", tint: .green)
                    StatusRow(title: "GPS", value: location == nil ? "SEARCHING" : "LOCKED", icon: "location.fill", tint: location == nil ? .orange : .green)
                    StatusRow(title: "Active sightings", value: "\(stats.activeSightings)", icon: "mappin.and.ellipse", tint: .orange)
                    StatusRow(title: "Confirmed", value: "\(stats.confirmedSightings)", icon: "checkmark.seal.fill", tint: .green)
                    StatusRow(title: "Hotspots", value: "\(stats.hotspots)", icon: "flame.fill", tint: .red)
                }
                Section("Threat Level") {
                    ThreatGauge(score: stats.confidence)
                }
                Section("Nearest Contacts") {
                    let nearest = sightings.compactMap { sighting -> (Sighting, Double)? in
                        guard let location else { return nil }
                        let d = location.distance(from: CLLocation(latitude: sighting.latitude, longitude: sighting.longitude)) / 1609.34
                        return (sighting, d)
                    }.sorted { $0.1 < $1.1 }.prefix(8)
                    if nearest.isEmpty { Text("No GPS-based contacts yet.").foregroundStyle(.secondary) }
                    ForEach(Array(nearest), id: \.0.id) { item in
                        let truck = trucks.first(where: { $0.id == item.0.truckId })
                        HStack {
                            Image(systemName: item.0.confidenceLevel == .confirmed ? "checkmark.seal.fill" : "mappin.circle.fill")
                                .foregroundStyle(item.0.confidenceLevel == .confirmed ? .green : .orange)
                            VStack(alignment: .leading) {
                                Text(truck?.name ?? "Unknown Truck").fontWeight(.semibold)
                                Text("\(item.1 < 0.1 ? "Very close" : String(format: "%.2f mi", item.1)) • \(item.0.timestamp, style: .relative)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(item.0.confidenceLevel.rawValue).font(.caption2.bold())
                        }
                    }
                }
            }
            .navigationTitle("Radar Command")
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

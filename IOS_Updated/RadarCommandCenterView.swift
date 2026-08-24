import SwiftUI
import CoreLocation

struct RadarCommandCenterView: View {
    let sightings: [Sighting]
    let location: CLLocation?
    let onRefresh: () -> Void
    @State private var sweep = false
    @State private var pulse = false

    private var stats: RadarStats { RadarEngine.shared.stats(sightings: sightings, location: location) }

    var body: some View {
        VStack(spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Label("RADAR ONLINE", systemImage: "dot.radiowaves.left.and.right")
                        .font(.caption.bold())
                        .foregroundStyle(.green)
                    Text("LIVE THREAT PICTURE")
                        .font(.caption2.monospaced().bold())
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: onRefresh) {
                    Image(systemName: "arrow.clockwise")
                        .font(.headline)
                }
                .buttonStyle(.bordered)
                .clipShape(Circle())
            }

            HStack(spacing: 14) {
                ZStack {
                    Circle().stroke(.green.opacity(0.22), lineWidth: 1)
                    Circle().stroke(.green.opacity(0.18), lineWidth: 1).padding(14)
                    Circle().stroke(.green.opacity(0.18), lineWidth: 1).padding(28)
                    Rectangle()
                        .fill(.green.opacity(0.18))
                        .frame(width: 2, height: 78)
                        .rotationEffect(.degrees(sweep ? 360 : 0), anchor: .bottom)
                        .animation(.linear(duration: 2.4).repeatForever(autoreverses: false), value: sweep)
                    Circle()
                        .fill(.green)
                        .frame(width: pulse ? 10 : 6)
                        .shadow(color: .green, radius: pulse ? 12 : 4)
                        .animation(.easeInOut(duration: 1).repeatForever(), value: pulse)
                }
                .frame(width: 96, height: 96)
                .background(.black.opacity(0.72), in: Circle())
                .overlay(Circle().stroke(.green.opacity(0.45), lineWidth: 1))

                VStack(alignment: .leading, spacing: 7) {
                    metric("ACTIVE", "\(stats.activeSightings)", "dot.radiowaves.left.and.right")
                    metric("CONFIRMED", "\(stats.confirmedSightings)", "checkmark.seal.fill")
                    metric("HOTSPOTS", "\(stats.hotspots)", "flame.fill")
                    metric("CONFIDENCE", "\(stats.confidence)%", "gauge.with.dots.needle.67percent")
                }
            }

            HStack {
                Label("Auto-scan", systemImage: "antenna.radiowaves.left.and.right")
                Spacer()
                Text(location == nil ? "Waiting for GPS" : "GPS LOCKED")
                    .font(.caption.bold())
                    .foregroundStyle(location == nil ? .orange : .green)
            }
            .font(.caption)
        }
        .padding(14)
        .background(.ultraThinMaterial)
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(.green.opacity(0.25), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .shadow(radius: 10)
        .onAppear { sweep = true; pulse = true }
    }

    private func metric(_ title: String, _ value: String, _ icon: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon).frame(width: 16)
            Text(title).font(.caption2.monospaced()).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.caption.bold().monospacedDigit())
        }
    }
}

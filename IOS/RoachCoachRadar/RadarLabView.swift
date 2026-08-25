import SwiftUI

struct RadarLabView: View {
    @StateObject private var vm = RadarLabViewModel()

    var body: some View {
        List {
            if let brief = vm.brief {
                Section("WHAT'S HOT") {
                    Label(brief.title, systemImage: "flame.fill")
                        .font(.headline)
                    Text(brief.detail)
                    Text("Signal score \(brief.score)%")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section("SYSTEM") {
                stat("Observations", vm.observations.count)
                stat("Hotspots", vm.hotspots.count)
                if let simulation = vm.simulation {
                    Text("Replay accuracy \(Int(simulation.accuracy * 100))%")
                }
                if let updated = vm.lastUpdated {
                    Text("Updated \(updated, style: .relative) ago")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section("HOTSPOTS") {
                if vm.hotspots.isEmpty {
                    Text("No active hotspots yet.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(vm.hotspots) { hotspot in
                        Label(
                            "\(hotspot.title) • \(hotspot.score)%",
                            systemImage: "flame"
                        )
                    }
                }
            }

            Section("SIMULATION") {
                Button("REPLAY CURRENT DATA") {
                    vm.replay()
                }
            }
        }
        .navigationTitle("Radar Lab")
        .task {
            vm.ingest([])
        }
    }

    private func stat(_ title: String, _ value: Int) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(String(value)).bold()
        }
    }
}

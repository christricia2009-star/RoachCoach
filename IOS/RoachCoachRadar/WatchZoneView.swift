import SwiftUI
import CoreLocation

struct WatchZoneView: View {
    @State private var trucks: [Truck] = []
    @State private var sightings: [Sighting] = []
    @Environment(\.dismiss) private var dismiss
    @State private var watched = Set<UUID>()

    var body: some View {
        NavigationStack {
            List {
                Section("½-mile watch zones") {
                    Text("Pick trucks you want the radar to watch. iOS can wake the app when you enter a monitored geographic region.").font(.footnote).foregroundStyle(.secondary)
                    ForEach(trucks) { truck in
                        let sighting = sightings.filter { $0.truckId == truck.id }.max { $0.timestamp < $1.timestamp }
                        HStack {
                            VStack(alignment: .leading) { Text(truck.name).bold(); Text(truck.cuisineType).font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            Toggle("", isOn: Binding(get: { watched.contains(truck.id) }, set: { enabled in
                                if enabled, let s = sighting { watched.insert(truck.id); GeofenceRadarService.shared.watch(id: truck.id, coordinate: s.coordinate, name: truck.name) }
                                else { watched.remove(truck.id); GeofenceRadarService.shared.stopWatching(id: truck.id) }
                            }))
                            .labelsHidden()
                        }
                    }
                }
            }
            .navigationTitle("Watch Zones")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task {
                GeofenceRadarService.shared.requestPermission()
                async let t = CloudKitService.shared.fetchTrucks()
                async let s = CloudKitService.shared.fetchSightings()
                trucks = (try? await t) ?? []
                sightings = (try? await s) ?? []
            }
        }
    }
}

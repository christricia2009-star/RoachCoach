import SwiftUI
import CoreLocation
import PhotosUI
import UIKit

struct ReportSightingView: View {
    let trucks: [Truck]
    var onSubmit: (Sighting) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selectedTruckId: UUID?
    @State private var newTruckName: String = ""
    @State private var note: String = ""
    @State private var selectedPhotoItem: PhotosPickerItem?
    @StateObject private var locationService = LocationService.shared
    @State private var latitude: Double = 38.5816
    @State private var longitude: Double = -121.4944

    var body: some View {
        NavigationStack {
            Form {
                Section("Which truck did you see?") {
                    Picker("Truck", selection: $selectedTruckId) {
                        Text("Select a truck").tag(UUID?.none)
                        ForEach(trucks) { truck in
                            Text(truck.name).tag(Optional(truck.id))
                        }
                    }

                    TextField("Or type a new truck name", text: $newTruckName)
                }

                Section("Details") {
                    TextField("Note (optional) e.g. 'parked outside the library'", text: $note, axis: .vertical)
                    PhotosPicker("Add a photo (optional)", selection: $selectedPhotoItem, matching: .images)
                }

                Section("Location") {
                    if locationService.currentLocation != nil {
                        Text("Using your current GPS pin.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("Waiting for GPS…")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                }

                Section {
                    Button("Submit Sighting") {
                        submit()
                    }
                    .disabled(selectedTruckId == nil && newTruckName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .navigationTitle("Report a Sighting")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .onAppear {
                locationService.requestPermission()
                if let loc = locationService.currentLocation {
                    latitude = loc.coordinate.latitude
                    longitude = loc.coordinate.longitude
                }
            }
        }
    }

    private func submit() {
        guard let truckId = selectedTruckId else {
            // In a full implementation, this would first call an endpoint to
            // create a new Truck record, then use its returned ID here.
            dismiss()
            return
        }

        let sighting = Sighting(
            truckId: truckId,
            latitude: latitude,
            longitude: longitude,
            note: note.isEmpty ? nil : note,
            confidenceLevel: .likely
        )

        // Real haptic feedback on submit — makes the report flow feel alive.
        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.success)

        onSubmit(sighting)
        dismiss()
    }
}

struct QuickCheckInView: View {
    let trucks: [Truck]
    var isOwner: Bool = false
    var onSubmit: (Sighting) -> Void

    @Environment(\.dismiss) private var dismiss
    @StateObject private var locationService = LocationService.shared
    @StateObject private var favorites = FavoritesStore.shared
    @State private var selectedTruckId: UUID?

    private var orderedTrucks: [Truck] {
        trucks.sorted { a, b in
            let aFav = favorites.contains(a.id)
            let bFav = favorites.contains(b.id)
            if aFav != bFav { return aFav && !bFav }
            return a.name.localizedCompare(b.name) == .orderedAscending
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section(isOwner ? "Which truck is yours?" : "Which truck are you at?") {
                    Picker("Truck", selection: $selectedTruckId) {
                        Text("Select a truck").tag(UUID?.none)
                        ForEach(orderedTrucks) { truck in
                            Text(truck.name).tag(Optional(truck.id))
                        }
                    }
                }
                Section("Location") {
                    if locationService.currentLocation != nil {
                        Text("Drops a pin at your current GPS.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("Waiting for GPS lock…")
                            .foregroundStyle(.orange)
                    }
                }
                Section {
                    Button(isOwner ? "We're here now" : "I'm here") {
                        submit()
                    }
                    .disabled(selectedTruckId == nil || locationService.currentLocation == nil)
                }
            }
            .navigationTitle(isOwner ? "Owner check-in" : "I'm here")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .onAppear { locationService.requestPermission() }
        }
    }

    private func submit() {
        guard let truckId = selectedTruckId,
              let loc = locationService.currentLocation else { return }
        let truckName = trucks.first(where: { $0.id == truckId })?.name
        let sighting = Sighting(
            truckId: truckId,
            latitude: loc.coordinate.latitude,
            longitude: loc.coordinate.longitude,
            note: isOwner ? "Owner check-in: \(truckName ?? "truck") is here now" : "I'm here at \(truckName ?? "this truck")",
            confidenceLevel: isOwner ? .confirmed : .likely
        )
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        onSubmit(sighting)
        dismiss()
    }
}

#Preview {
    ReportSightingView(trucks: MockDataService.shared.trucks) { _ in }
}

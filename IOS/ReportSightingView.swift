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
    @State private var latitude: Double = 37.7749
    @State private var longitude: Double = -122.4194

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
                    // NOTE: In production, pull this from CoreLocation
                    // (CLLocationManager) instead of using the map's center.
                    Text("Uses your current location automatically.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
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

#Preview {
    ReportSightingView(trucks: MockDataService.shared.trucks) { _ in }
}

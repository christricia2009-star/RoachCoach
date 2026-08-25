import SwiftUI

/// PHASE 2 FEATURE — placeholder UI with a toy heuristic, not real ML.
///
/// Intent: once enough historical sighting data exists, predict where a
/// truck is LIKELY to be based on day-of-week patterns, rather than only
/// showing where it's been seen today. Replace `predict(for:)` with a real
/// model (even a simple day-of-week frequency count server-side) once
/// there's enough data to make predictions meaningful.
struct PredictiveScheduleView: View {
    @State private var trucks: [Truck] = []
    private let api: APIServicing = LiveAPIService.shared

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Predictions are most useful after a truck has several weeks of sighting history. This is a placeholder until real historical data is available.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                ForEach(trucks) { truck in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(truck.name).fontWeight(.semibold)
                        Text(predict(for: truck))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                }
            }
            .navigationTitle("Predicted Locations")
            .task {
                trucks = (try? await api.fetchTrucks()) ?? []
            }
        }
    }

    private func predict(for truck: Truck) -> String {
        // Toy placeholder heuristic — NOT a real model.
        let weekday = Calendar.current.component(.weekday, from: Date())
        let likelyArea = ["Downtown Plaza", "Tech Park Row", "Riverside Lot", "Market Street"][weekday % 4]
        return "Likely near \(likelyArea) today, based on past patterns."
    }
}

#Preview {
    PredictiveScheduleView()
}

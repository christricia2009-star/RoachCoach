import SwiftUI
import Charts

/// A real, working chart (Swift Charts, iOS 16+) showing how many
/// confirmed/likely sightings a truck had per day over the last 14 days.
/// Built from actual Sighting data — swap the mock backfill in
/// MockDataService for real historical data once the live backend exists,
/// and this chart keeps working unchanged.
struct TruckReliabilityChartView: View {
    let sightings: [Sighting]

    private struct DayCount: Identifiable {
        let id = UUID()
        let day: Date
        let count: Int
    }

    private var dailyCounts: [DayCount] {
        let calendar = Calendar.current
        let grouped = Dictionary(grouping: sightings) { sighting in
            calendar.startOfDay(for: sighting.timestamp)
        }
        return grouped.map { DayCount(day: $0.key, count: $0.value.count) }
            .sorted { $0.day < $1.day }
            .suffix(14)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Sighting Activity (Last 14 Days)")
                .font(.subheadline)
                .fontWeight(.semibold)

            if dailyCounts.isEmpty {
                Text("No sighting history yet.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(height: 140)
            } else {
                Chart(dailyCounts) { entry in
                    BarMark(
                        x: .value("Day", entry.day, unit: .day),
                        y: .value("Sightings", entry.count)
                    )
                    .foregroundStyle(Color.orange.gradient)
                    .cornerRadius(4)
                }
                .chartXAxis {
                    AxisMarks(values: .stride(by: .day, count: 3)) { _ in
                        AxisValueLabel(format: .dateTime.month().day())
                    }
                }
                .frame(height: 140)
            }
        }
    }
}

#Preview {
    TruckReliabilityChartView(sightings: MockDataService.shared.sightings)
        .padding()
}

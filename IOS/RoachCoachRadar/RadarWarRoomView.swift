import SwiftUI
import MapKit

struct RadarWarRoomView: View {
    @State private var trucks: [Truck] = []
    @State private var sightings: [Sighting] = []
    @State private var selectedTruck: Truck?
    @State private var showIntercept = false
    @State private var isLoading = true
    @StateObject private var accuracy = PredictionAccuracyStore.shared
    @StateObject private var locationService = LocationService.shared
    @Environment(\.dismiss) private var dismiss

    private var brain: [BrainPrediction] { RadarBrain.shared.analyze(trucks: trucks, sightings: sightings) }
    private var anomalies: [RadarAnomaly] { AnomalyRadarService.shared.detect(trucks: trucks, sightings: sightings) }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("AI RADAR BRAIN", systemImage: "brain.head.profile").font(.headline)
                        Text("Explainable on-device intelligence combines recency, time patterns, confidence and movement history. No external AI service is required.").font(.caption).foregroundStyle(.secondary)
                        HStack {
                            metric("Predictions", "\(accuracy.predictions)")
                            metric("Accuracy", accuracy.predictions == 0 ? "—" : "\(accuracy.accuracy)%")
                            metric("Anomalies", "\(anomalies.count)")
                        }
                    }.padding(.vertical, 4)
                }
                Section("Predictive Trails") {
                    ForEach(brain.prefix(8)) { item in
                        VStack(alignment: .leading, spacing: 7) {
                            HStack { Text(item.truck.name).bold(); Spacer(); Text("\(item.prediction.confidence)%").foregroundStyle(.green).bold() }
                            Text("\(item.prediction.windowStart, style: .time)–\(item.prediction.windowEnd, style: .time)").font(.caption)
                            Text(item.prediction.evidence.joined(separator: " • ")).font(.caption2).foregroundStyle(.secondary)
                            Button("Plan Intercept") { selectedTruck = item.truck; showIntercept = true }
                                .buttonStyle(.borderedProminent)
                        }.padding(.vertical, 5)
                    }
                    if brain.isEmpty { Text("Not enough history yet. Submit a few sightings and Radar Brain will learn from them.").foregroundStyle(.secondary) }
                }
                Section("Anomaly Detector") {
                    if anomalies.isEmpty { Label("No unusual movement detected", systemImage: "checkmark.seal.fill").foregroundStyle(.green) }
                    ForEach(anomalies) { anomaly in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack { Text(anomaly.truck.name).bold(); Spacer(); Text("\(anomaly.score)/100").foregroundStyle(.orange).bold() }
                            Text(anomaly.message).font(.caption).foregroundStyle(.secondary)
                        }.padding(.vertical, 3)
                    }
                }
                Section("Self-Check") {
                    Text("Radar can grade a prediction when you compare it with a later real sighting.").font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Button("Mark Hit") { accuracy.record(hit: true) }.buttonStyle(.bordered)
                        Button("Mark Miss") { accuracy.record(hit: false) }.buttonStyle(.bordered)
                    }
                }
            }
            .navigationTitle("AI Radar War Room")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { await load() }
            .sheet(isPresented: $showIntercept) {
                if let selectedTruck, let plan = InterceptEngine.shared.plan(for: selectedTruck, sightings: sightings, userLocation: locationService.currentLocation) {
                    InterceptPlanView(plan: plan)
                }
            }
        }
    }

    @ViewBuilder private func metric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading) { Text(value).font(.title3.bold()); Text(title).font(.caption2).foregroundStyle(.secondary) }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func load() async {
        isLoading = true; defer { isLoading = false }
        async let t = CloudKitService.shared.fetchTrucks()
        async let s = CloudKitService.shared.fetchSightings()
        trucks = (try? await t) ?? []; sightings = (try? await s) ?? []
    }
}

private struct InterceptPlanView: View {
    let plan: InterceptPlan
    @Environment(\.dismiss) private var dismiss
    @State private var position: MapCameraPosition

    init(plan: InterceptPlan) {
        self.plan = plan
        _position = State(initialValue: .region(MKCoordinateRegion(center: plan.coordinate, span: MKCoordinateSpan(latitudeDelta: 0.025, longitudeDelta: 0.025))))
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Map(position: $position) {
                    Marker(plan.truck.name, coordinate: plan.coordinate)
                }.frame(height: 300)
                VStack(alignment: .leading, spacing: 14) {
                    Label("INTERCEPT PLAN", systemImage: "scope").font(.headline)
                    Text(plan.truck.name).font(.title2.bold())
                    HStack { Text("Confidence"); Spacer(); Text("\(plan.confidence)%").bold().foregroundStyle(.green) }
                    HStack { Text("Predicted arrival"); Spacer(); Text(plan.eta, style: .time).bold() }
                    if let miles = plan.distanceMiles { HStack { Text("Distance"); Spacer(); Text(String(format: "%.1f mi", miles)).bold() } }
                    Text(plan.reason).font(.callout).foregroundStyle(.secondary)
                    Button("Open in Maps") {
                        let location = CLLocation(latitude: plan.coordinate.latitude, longitude: plan.coordinate.longitude)
                        let item = MKMapItem(location: location, address: nil)
                        item.name = plan.truck.name
                        item.openInMaps()
                    }.buttonStyle(.borderedProminent)
                }.padding()
                Spacer()
            }
            .navigationTitle("Intercept")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}

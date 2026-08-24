import SwiftUI
import MapKit

struct MapContentView: View {
    @State private var position: MapCameraPosition = .automatic
    @State private var trucks: [Truck] = []
    @State private var sightings: [Sighting] = []
    @State private var selectedSighting: Sighting?
    @State private var showReportSheet = false
    @State private var showRadarDetails = false
    @State private var showHot = false
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var selectedCuisine: String?
    @State private var lastUpdated = Date()
    @State private var timeMachineMinutes = 0
    @State private var radarScanSightings: [Sighting] = []
    @State private var radarScanObservations: [RadarObservation] = []
    @State private var scanStatusMessage: String?
    @State private var scanErrorMessage: String?
    @State private var showScanError = false
    @AppStorage("radar.scanRadius") private var scanRadius = 10.0
    @AppStorage("radar.autoScan") private var autoScan = false
    @StateObject private var locationService = LocationService.shared
    @StateObject private var radarScanner = RadarScanService.shared
    private let api: APIServicing = CloudKitService.shared

    private var cuisines: [String] { Array(Set(trucks.map(\.cuisineType))).sorted() }
    // Sightings shown on the map/list are CloudKit sightings merged with
    // whatever the last backend radar scan returned. Kept as separate
    // @State arrays (rather than appending into `sightings` directly) so
    // that `loadData()` re-fetching from CloudKit doesn't wipe out what a
    // scan just found.
    private var allSightings: [Sighting] {
        var merged: [UUID: Sighting] = [:]
        for sighting in sightings { merged[sighting.id] = sighting }
        for sighting in radarScanSightings { merged[sighting.id] = sighting }
        return Array(merged.values)
    }
    private var filteredSightings: [Sighting] {
        allSightings.filter { sighting in
            guard let truck = trucks.first(where: { $0.id == sighting.truckId }) else { return false }
            let search = searchText.isEmpty || truck.name.localizedCaseInsensitiveContains(searchText) || truck.cuisineType.localizedCaseInsensitiveContains(searchText)
            return search && (selectedCuisine == nil || truck.cuisineType == selectedCuisine)
        }
    }
    private var replayDate: Date { Date().addingTimeInterval(Double(timeMachineMinutes) * 60) }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Map(position: $position) {
                    UserAnnotation()
                    ForEach(filteredSightings) { sighting in
                        Annotation(truckName(for: sighting), coordinate: sighting.coordinate) {
                            SightingPinView(sighting: sighting, truckName: truckName(for: sighting))
                                .onTapGesture { selectedSighting = sighting }
                        }
                    }
                }
                .mapControls { MapCompass(); MapUserLocationButton(); MapScaleView() }
                .ignoresSafeArea(edges: .bottom)

                VStack(spacing: 10) {
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                        TextField("Search trucks, cuisine…", text: $searchText)
                        if !searchText.isEmpty { Button { searchText = "" } label: { Image(systemName: "xmark.circle.fill") }.foregroundStyle(.secondary) }
                    }
                    .padding(10).background(.regularMaterial).clipShape(RoundedRectangle(cornerRadius: 12))

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            FilterChip(label: "All", isSelected: selectedCuisine == nil) { selectedCuisine = nil }
                            ForEach(cuisines, id: \.self) { cuisine in FilterChip(label: cuisine, isSelected: selectedCuisine == cuisine) { selectedCuisine = selectedCuisine == cuisine ? nil : cuisine } }
                        }
                    }

                    NearbySummaryBar(
                        truckCount: trucks.count,
                        activeCount: allSightings.filter { !$0.isExpired }.count,
                        isScanning: radarScanner.isScanning,
                        onScan: { Task { await scanNow() } },
                        onDetails: { showRadarDetails = true }
                    )
                    .disabled(locationService.currentLocation == nil && !radarScanner.isScanning)
                    if let scanStatusMessage {
                        Text(scanStatusMessage).font(.caption2).foregroundStyle(.secondary)
                    }

                    HStack(spacing: 8) {
                        Button { showHot = true } label: { Label("WHAT'S HOT", systemImage: "flame.fill") }.buttonStyle(.borderedProminent)
                        Button { showRadarDetails = true } label: { Label("RECON", systemImage: "scope") }.buttonStyle(.bordered)
                    }

                    VStack(spacing: 2) {
                        HStack { Text(timeMachineMinutes == 0 ? "NOW" : replayDate.formatted(date: .omitted, time: .shortened)).font(.caption.bold().monospacedDigit()); Spacer(); Text("TIME MACHINE").font(.caption2.monospaced()).foregroundStyle(.secondary) }
                        Slider(value: Binding(get: { Double(timeMachineMinutes) }, set: { timeMachineMinutes = Int($0.rounded()) }), in: -180...240, step: 15)
                    }.padding(10).background(.regularMaterial).clipShape(RoundedRectangle(cornerRadius: 12))
                }.padding()

                VStack { Spacer(); HStack { Spacer(); VStack(spacing: 10) {
                    Button { position = .userLocation(fallback: .automatic) } label: { Image(systemName: "location.fill").font(.title3).frame(width: 48,height:48).background(.regularMaterial,in:Circle()) }
                    Button { showReportSheet = true } label: { Image(systemName: "plus.circle.fill").resizable().frame(width:58,height:58).foregroundStyle(.white,.orange).shadow(radius:5) }
                }.padding(.trailing).padding(.bottom,100) } }

                if radarScanner.isScanning { VStack(spacing:8) { ProgressView(); Text("LIVE RADAR SCAN").font(.caption.bold()); Text("Evidence • cameras • sources • predictions").font(.caption2).foregroundStyle(.secondary) }.padding(14).background(.regularMaterial).clipShape(RoundedRectangle(cornerRadius:14)).shadow(radius:4).padding(.top,150) }
                if isLoading { ProgressView("Loading radar…").padding().background(.regularMaterial).clipShape(RoundedRectangle(cornerRadius:12)) }
            }
            .navigationTitle("Roach Coach Radar")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { HStack(spacing:4) { Circle().fill(.green).frame(width:7,height:7); Text(lastUpdated,style:.time).font(.caption2.monospacedDigit()).foregroundStyle(.secondary) } } }
            .task { locationService.requestPermission(); await loadData(); if autoScan { await scanNow() } }
            .refreshable { await loadData() }
            .sheet(item: $selectedSighting) { sighting in if let truck = trucks.first(where: {$0.id == sighting.truckId}) { TruckProfileView(truck:truck) } }
            .sheet(isPresented: $showReportSheet) { ReportSightingView(trucks:trucks) { newSighting in Task { try? await api.submitSighting(newSighting); NotificationService.shared.scheduleTruckSpottedNotification(truckName:truckName(for:newSighting),note:"A fresh radar report just landed.",delaySeconds:1); await loadData() } } }
            .sheet(isPresented: $showRadarDetails) { RadarDetailsView(trucks:trucks,sightings:sightings,location:locationService.currentLocation) }
            .sheet(isPresented: $showHot) { NavigationStack { WhatIsHotView(observations: radarObservations()) } }
            .alert("Radar Scan Failed", isPresented: $showScanError, presenting: scanErrorMessage) { _ in
                Button("OK", role: .cancel) {}
            } message: { message in
                Text(message)
            }
        }
    }
    private func truckName(for sighting:Sighting)->String { trucks.first(where:{$0.id==sighting.truckId})?.name ?? "Unknown Truck" }
    private func radarObservations()->[RadarObservation] {
        let fromSightings = allSightings.map { RadarObservation(truckID:$0.truckId,source:.userReport,sourceID:$0.id.uuidString,observedAt:$0.timestamp,latitude:$0.latitude,longitude:$0.longitude,text:$0.note,rawConfidence:$0.confidenceLevel == .confirmed ? 0.95 : 0.65) }
        var merged: [UUID: RadarObservation] = [:]
        for observation in fromSightings { merged[observation.id] = observation }
        for observation in radarScanObservations { merged[observation.id] = observation }
        return Array(merged.values)
    }
    private func scanNow() async {
        guard let location = locationService.currentLocation else { return }
        if let result = await radarScanner.scan(location: location, radiusMiles: scanRadius) {
            radarScanSightings = result.sightings
            radarScanObservations = result.observations
            scanStatusMessage = "Scan found \(result.sightings.count) sighting(s), \(result.observations.count) observation(s) · \(result.summary)"
        } else {
            scanStatusMessage = nil
            scanErrorMessage = radarScanner.lastError ?? "Radar scan failed for an unknown reason."
            showScanError = true
        }
        await loadData()
    }
    private func loadData() async { isLoading=true; defer{isLoading=false;lastUpdated=Date()}; do { async let a=api.fetchTrucks(); async let b=api.fetchSightings(); trucks=try await a; sightings=try await b } catch { print("Radar load failed: \(error)") } }
}

/// Replaces the old "RADAR ONLINE / 0 / 0 / 0 / 0%" panel as the first thing
/// people see. Leads with something that's actually true and useful — how
/// many trucks exist and how many sightings are active right now — instead
/// of automated-detection counters that read as broken when they're at
/// zero (which, given today's data sources, is most of the time). Full
/// detail is one tap away via "Details".
private struct NearbySummaryBar: View {
    let truckCount: Int
    let activeCount: Int
    let isScanning: Bool
    let onScan: () -> Void
    let onDetails: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Image(systemName: "truck.box.fill").foregroundStyle(.orange)
                    Text("\(truckCount) truck\(truckCount == 1 ? "" : "s") tracked")
                        .font(.subheadline.weight(.semibold))
                }
                Text(activeCount > 0
                     ? "\(activeCount) active sighting\(activeCount == 1 ? "" : "s") right now"
                     : "No active sightings — tap Scan to check nearby signals")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button(action: onDetails) {
                Image(systemName: "chevron.right.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.secondary)
            }

            Button(action: onScan) {
                if isScanning {
                    ProgressView().tint(.white).frame(width: 20, height: 20)
                } else {
                    Label("SCAN", systemImage: "antenna.radiowaves.left.and.right")
                        .font(.caption.bold())
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(.orange, in: Capsule())
            .foregroundStyle(.white)
            .disabled(isScanning)
        }
        .padding(12)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

private struct FilterChip:View { let label:String; let isSelected:Bool; let action:()->Void; var body:some View { Button(action:action){ Text(label).font(.footnote.weight(.medium)).padding(.horizontal,12).padding(.vertical,6).background(isSelected ? Color.orange : Color(.systemBackground).opacity(0.9)).foregroundStyle(isSelected ? .white : .primary).clipShape(Capsule()) } } }
private struct SightingPinView:View { let sighting:Sighting; let truckName:String; @State private var pulse=false; var body:some View { VStack(spacing:2){ Text(truckName).font(.caption2.bold()).padding(.horizontal,6).padding(.vertical,2).background(.thinMaterial).clipShape(Capsule()); ZStack { if sighting.confidenceLevel == .confirmed { Circle().fill(.green.opacity(0.35)).frame(width:pulse ? 48:28,height:pulse ? 48:28).animation(.easeInOut(duration:1.2).repeatForever(autoreverses:true),value:pulse) }; Image(systemName:sighting.confidenceLevel == .confirmed ? "mappin.and.ellipse":"mappin.circle.fill").resizable().frame(width:28,height:28).foregroundStyle(color(for:sighting.confidenceLevel)) }.onAppear{pulse=true} } } ; private func color(for l:ConfidenceLevel)->Color { l == .confirmed ? .green : l == .likely ? .orange : .gray } }

#Preview { MapContentView() }

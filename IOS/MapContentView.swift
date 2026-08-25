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
            if sighting.isExpired && timeMachineMinutes == 0 { return false }
            let truck = trucks.first(where: { $0.id == sighting.truckId })
            if let selectedCuisine {
                guard truck?.cuisineType == selectedCuisine else { return false }
            }
            if searchText.isEmpty { return true }
            let haystack = "\(truck?.name ?? "") \(truck?.cuisineType ?? "") \(sighting.note ?? "")"
            return haystack.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var listingObservations: [RadarObservation] {
        radarScanObservations.filter { observation in
            if searchText.isEmpty { return true }
            let haystack = "\(observation.text ?? "") \(observation.source.rawValue)"
            return haystack.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var activeSightingCount: Int {
        allSightings.filter { !$0.isExpired }.count
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
                    ForEach(listingObservations) { observation in
                        Annotation(listingTitle(for: observation), coordinate: observation.coordinate) {
                            ListingPinView(title: listingTitle(for: observation))
                        }
                    }
                }
                .mapControls { MapCompass(); MapUserLocationButton(); MapScaleView() }
                .ignoresSafeArea(edges: .bottom)

                VStack(spacing: 8) {
                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                        TextField("Search…", text: $searchText)
                        if !searchText.isEmpty {
                            Button { searchText = "" } label: { Image(systemName: "xmark.circle.fill") }
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background(.regularMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                    if !cuisines.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                FilterChip(label: "All", isSelected: selectedCuisine == nil) { selectedCuisine = nil }
                                ForEach(cuisines, id: \.self) { cuisine in
                                    FilterChip(label: cuisine, isSelected: selectedCuisine == cuisine) {
                                        selectedCuisine = selectedCuisine == cuisine ? nil : cuisine
                                    }
                                }
                            }
                        }
                    }

                    NearbySummaryBar(
                        truckCount: trucks.count,
                        activeCount: activeSightingCount,
                        listingCount: listingObservations.count,
                        isScanning: radarScanner.isScanning,
                        onScan: { Task { await scanNow() } },
                        onDetails: { showRadarDetails = true }
                    )
                    .disabled(locationService.currentLocation == nil && !radarScanner.isScanning)

                    if let scanStatusMessage {
                        Text(scanStatusMessage)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    Spacer()
                }
                .padding(.horizontal, 12)
                .padding(.top, 8)

                VStack { Spacer(); HStack { Spacer(); VStack(spacing: 10) {
                    Button { position = .userLocation(fallback: .automatic) } label: { Image(systemName: "location.fill").font(.title3).frame(width: 48,height:48).background(.regularMaterial,in:Circle()) }
                    Button { showReportSheet = true } label: { Image(systemName: "plus.circle.fill").resizable().frame(width:58,height:58).foregroundStyle(.white,.orange).shadow(radius:5) }
                }.padding(.trailing).padding(.bottom,100) } }

                if radarScanner.isScanning { VStack(spacing:8) { ProgressView(); Text("LIVE RADAR SCAN").font(.caption.bold()); Text("Evidence • cameras • sources • predictions").font(.caption2).foregroundStyle(.secondary) }.padding(14).background(.regularMaterial).clipShape(RoundedRectangle(cornerRadius:14)).shadow(radius:4).padding(.top,150) }
                if isLoading { ProgressView("Loading radar…").padding().background(.regularMaterial).clipShape(RoundedRectangle(cornerRadius:12)) }
            }
            .navigationTitle("Radar")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    HStack(spacing: 4) {
                        Circle().fill(.green).frame(width: 7, height: 7)
                        Text(lastUpdated, style: .time)
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    HStack(spacing: 12) {
                        Button { showHot = true } label: {
                            Image(systemName: "flame.fill")
                        }
                        Button { showRadarDetails = true } label: {
                            Image(systemName: "list.bullet.rectangle")
                        }
                        Menu {
                            Text(timeMachineMinutes == 0 ? "Live now" : replayDate.formatted(date: .omitted, time: .shortened))
                            Slider(
                                value: Binding(
                                    get: { Double(timeMachineMinutes) },
                                    set: { timeMachineMinutes = Int($0.rounded()) }
                                ),
                                in: -180...240,
                                step: 15
                            )
                            Button("Reset to now") { timeMachineMinutes = 0 }
                        } label: {
                            Image(systemName: "clock")
                        }
                    }
                }
            }
            .task { locationService.requestPermission(); await loadData(); if autoScan { await scanNow() } }
            .refreshable { await loadData() }
            .sheet(item: $selectedSighting) { sighting in
                if let truck = trucks.first(where: { $0.id == sighting.truckId }) {
                    TruckProfileView(truck: truck)
                } else {
                    NavigationStack {
                        List {
                            Text(truckName(for: sighting))
                                .font(.headline)
                            if let note = sighting.note {
                                Text(note)
                            }
                            Text("\(sighting.latitude), \(sighting.longitude)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .navigationTitle("Listing")
                    }
                }
            }
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
    private func truckName(for sighting: Sighting) -> String {
        trucks.first(where: { $0.id == sighting.truckId })?.name ?? sighting.note ?? "Sighting"
    }

    private func listingTitle(for observation: RadarObservation) -> String {
        if let text = observation.text, !text.isEmpty {
            let first = text.split(separator: ",").first.map(String.init) ?? text
            return String(first.prefix(28))
        }
        return observation.source.rawValue.capitalized
    }
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
    let listingCount: Int
    let isScanning: Bool
    let onScan: () -> Void
    let onDetails: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button(action: onDetails) {
                HStack(spacing: 10) {
                    compactStat("\(activeCount)", "sightings", "mappin.circle.fill", .green)
                    compactStat("\(listingCount)", "listings", "list.bullet", .orange)
                    compactStat("\(truckCount)", "trucks", "truck.box.fill", .secondary)
                }
            }
            .buttonStyle(.plain)

            Spacer(minLength: 8)

            Button(action: onScan) {
                if isScanning {
                    ProgressView().tint(.white).frame(width: 18, height: 18)
                } else {
                    Text("SCAN")
                        .font(.caption.bold())
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.orange, in: Capsule())
            .foregroundStyle(.white)
            .disabled(isScanning)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func compactStat(_ value: String, _ label: String, _ icon: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 3) {
                Image(systemName: icon).foregroundStyle(color).font(.caption2)
                Text(value).font(.subheadline.weight(.bold).monospacedDigit())
            }
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }
}

private struct FilterChip:View { let label:String; let isSelected:Bool; let action:()->Void; var body:some View { Button(action:action){ Text(label).font(.footnote.weight(.medium)).padding(.horizontal,12).padding(.vertical,6).background(isSelected ? Color.orange : Color(.systemBackground).opacity(0.9)).foregroundStyle(isSelected ? .white : .primary).clipShape(Capsule()) } } }
private struct SightingPinView: View {
    let sighting: Sighting
    let truckName: String
    var body: some View {
        VStack(spacing: 2) {
            Text(truckName)
                .font(.caption2.bold())
                .lineLimit(1)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(.thinMaterial)
                .clipShape(Capsule())
            Image(systemName: "mappin.circle.fill")
                .font(.title2)
                .foregroundStyle(sighting.confidenceLevel == .confirmed ? .green : .orange)
        }
    }
}

private struct ListingPinView: View {
    let title: String
    var body: some View {
        VStack(spacing: 2) {
            Text(title)
                .font(.caption2.bold())
                .lineLimit(1)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(.thinMaterial)
                .clipShape(Capsule())
            Image(systemName: "signpost.right.fill")
                .font(.title3)
                .foregroundStyle(.blue)
        }
    }
}

#Preview { MapContentView() }

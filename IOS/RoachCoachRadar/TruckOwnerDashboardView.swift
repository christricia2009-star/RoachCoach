import SwiftUI

struct TruckOwnerDashboardView: View {
    @AppStorage("owner.claimedTruckId") private var claimedTruckId = ""
    @State private var trucks: [Truck] = []
    @State private var pendingSightings: [Sighting] = []
    @State private var orders: [Order] = []
    @State private var menu: [MenuItem] = []
    @State private var showWiFiConsent = false
    @State private var showDebugSeed = false
    @State private var showWereHere = false
    @State private var statusMessage: String?
    @State private var newItemName = ""
    @State private var newItemPrice = "10.00"
    @ObservedObject private var wifiService = WiFiDetectionService.shared
    @StateObject private var locationService = LocationService.shared
    private let api: APIServicing = CloudKitService.shared
    private var cloud: CloudKitService { CloudKitService.shared }

    private var claimedTruck: Truck? {
        trucks.first { $0.id.uuidString == claimedTruckId }
    }

    var body: some View {
        NavigationStack {
            List {
                if claimedTruck == nil {
                    Section("Claim your truck") {
                        Text("Pick your truck, then tap We’re here now to drop a confirmed pin at your GPS. Customers see it immediately.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Picker("My truck", selection: $claimedTruckId) {
                            Text("Select…").tag("")
                            ForEach(trucks) { truck in
                                Text(truck.name).tag(truck.id.uuidString)
                            }
                        }
                    }
                } else if let truck = claimedTruck {
                    Section("Live pin") {
                        Text(truck.name).font(.headline)
                        Button("We're here now") {
                            showWereHere = true
                        }
                        .disabled(locationService.currentLocation == nil)
                        if let statusMessage {
                            Text(statusMessage).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    Section("Order board") {
                        if orders.isEmpty {
                            Text("No live orders.")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(orders) { order in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text(order.status.displayName).fontWeight(.semibold)
                                        Spacer()
                                        Text(order.totalDisplay)
                                    }
                                    Text(order.customerName ?? "Walk-up")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    ForEach(order.items) { line in
                                        Text("\(line.quantity)× \(line.nameSnapshot)")
                                            .font(.caption)
                                    }
                                    HStack {
                                        ForEach(order.status.nextStatuses, id: \.self) { next in
                                            Button(next.displayName) {
                                                Task {
                                                    _ = try? await api.updateOrderStatus(orderId: order.id, status: next, pickupEtaMinutes: 10)
                                                    await refreshOwner(truck)
                                                }
                                            }
                                            .buttonStyle(.bordered)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Section("Menu") {
                        ForEach(menu) { item in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(item.name)
                                    Text(item.priceDisplay).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Toggle("In", isOn: Binding(
                                    get: { item.isAvailable },
                                    set: { on in
                                        var updated = item
                                        updated.isAvailable = on
                                        Task {
                                            try? await cloud.saveMenuItem(updated)
                                            await refreshOwner(truck)
                                        }
                                    }
                                ))
                                .labelsHidden()
                            }
                        }
                        TextField("New item name", text: $newItemName)
                        TextField("Price", text: $newItemPrice)
                            .keyboardType(.decimalPad)
                        Button("Add menu item") {
                            Task { await addMenuItem(for: truck) }
                        }
                        .disabled(newItemName.trimmingCharacters(in: .whitespaces).isEmpty)
                    }

                    Section("Pending customer reports") {
                        if pendingSightings.isEmpty {
                            Text("No pending sightings to review.")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(pendingSightings) { sighting in
                                Text(sighting.note ?? "Sighting reported")
                            }
                        }
                    }
                }

                Section("Detection Settings") {
                    HStack {
                        Label("Wi-Fi Truck Detection", systemImage: "wifi")
                        Spacer()
                        Text(wifiService.hasUserConsented ? "On" : "Off")
                            .foregroundStyle(.secondary)
                    }
                    Button(wifiService.hasUserConsented ? "Review Notice" : "Turn On…") {
                        showWiFiConsent = true
                    }
                }

                Section("Debug / Setup") {
                    Text("Map showing no data? Use this to confirm CloudKit reads/writes are actually working.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button("Seed Test Data Into CloudKit") {
                        showDebugSeed = true
                    }
                }
            }
            .navigationTitle("Owner Dashboard")
            .task {
                locationService.requestPermission()
                trucks = (try? await api.fetchTrucks()) ?? []
                if let truck = claimedTruck {
                    await refreshOwner(truck)
                }
            }
            .onChange(of: claimedTruckId) { _, _ in
                Task {
                    if let truck = claimedTruck {
                        await refreshOwner(truck)
                    }
                }
            }
            .sheet(isPresented: $showWiFiConsent) {
                WiFiConsentView()
            }
            .sheet(isPresented: $showDebugSeed) {
                DebugSeedDataView()
            }
            .sheet(isPresented: $showWereHere) {
                QuickCheckInView(trucks: claimedTruck.map { [$0] } ?? trucks, isOwner: true) { sighting in
                    Task {
                        try? await api.submitSighting(sighting)
                        statusMessage = "Live pin dropped. Customers can see you now."
                        pendingSightings = (try? await api.fetchSightings(forTruck: sighting.truckId)) ?? []
                    }
                }
            }
        }
    }

    private func refreshOwner(_ truck: Truck) async {
        pendingSightings = (try? await api.fetchSightings(forTruck: truck.id)) ?? []
        orders = (try? await api.fetchOrders(forTruck: truck.id, activeOnly: true)) ?? []
        menu = (try? await api.fetchMenu(forTruck: truck.id, availableOnly: false)) ?? []
    }

    private func addMenuItem(for truck: Truck) async {
        let cents = Int((Double(newItemPrice) ?? 10) * 100)
        let item = MenuItem(
            id: "menu_\(truck.id.uuidString.prefix(8))_\(UUID().uuidString.prefix(8))",
            truckId: truck.id.uuidString,
            name: newItemName.trimmingCharacters(in: .whitespacesAndNewlines),
            category: .entree,
            priceCents: cents,
            sortOrder: menu.count
        )
        try? await cloud.saveMenuItem(item)
        newItemName = ""
        await refreshOwner(truck)
    }
}

#Preview {
    TruckOwnerDashboardView()
}

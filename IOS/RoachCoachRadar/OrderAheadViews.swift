import SwiftUI

struct CartLine: Identifiable, Hashable {
    let id: String
    let item: MenuItem
    var quantity: Int
    var modifiers: [MenuItemModifier]

    var lineTotalCents: Int {
        let extra = modifiers.reduce(0) { $0 + $1.priceDeltaCents }
        return (item.priceCents + extra) * quantity
    }
}

struct TruckMenuSection: View {
    let items: [MenuItem]
    var onAdd: (MenuItem, [MenuItemModifier]) -> Void

    var body: some View {
        let grouped = Dictionary(grouping: items.filter(\.isAvailable), by: \.category)
        ForEach(MenuCategory.allCases, id: \.self) { category in
            if let rows = grouped[category], !rows.isEmpty {
                Section(category.displayName) {
                    ForEach(rows) { item in
                        MenuRow(item: item, onAdd: onAdd)
                    }
                }
            }
        }
    }
}

private struct MenuRow: View {
    let item: MenuItem
    var onAdd: (MenuItem, [MenuItemModifier]) -> Void
    @State private var picked: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.name).font(.body.weight(.semibold))
                    if let description = item.description {
                        Text(description).font(.caption).foregroundStyle(.secondary)
                    }
                    Text(item.priceDisplay).font(.subheadline).foregroundStyle(.orange)
                }
                Spacer()
                Button("Add") {
                    let mods = item.modifiers.filter { picked.contains($0.name) }
                    onAdd(item, mods)
                }
                .buttonStyle(.borderedProminent)
                .tint(.orange)
            }
            if !item.modifiers.isEmpty {
                ForEach(item.modifiers, id: \.name) { mod in
                    Toggle(isOn: Binding(
                        get: { picked.contains(mod.name) },
                        set: { on in
                            if on { picked.insert(mod.name) } else { picked.remove(mod.name) }
                        }
                    )) {
                        Text(mod.priceDeltaCents == 0 ? mod.name : "\(mod.name) +\(String(format: "$%.2f", Double(mod.priceDeltaCents) / 100))")
                            .font(.caption)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }
}

struct CartCheckoutSheet: View {
    let truck: Truck
    @Binding var cart: [CartLine]
    var onPlaced: (Order) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var notes = ""
    @State private var tipPercent = 15
    @State private var placing = false
    @State private var error: String?
    @State private var placed: Order?
    private let api: APIServicing = CloudKitService.shared

    private var subtotal: Int { cart.reduce(0) { $0 + $1.lineTotalCents } }
    private var tax: Int { Int((Double(subtotal) * 0.0875).rounded()) }
    private var tip: Int { Int((Double(subtotal) * Double(tipPercent) / 100).rounded()) }
    private var total: Int { subtotal + tax + tip }

    var body: some View {
        NavigationStack {
            List {
                Section("Your order") {
                    ForEach($cart) { $line in
                        Stepper(value: $line.quantity, in: 1...20) {
                            VStack(alignment: .leading) {
                                Text(line.item.name)
                                Text(String(format: "$%.2f", Double(line.lineTotalCents) / 100))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .onDelete { cart.remove(atOffsets: $0) }
                }
                Section("Pickup") {
                    TextField("Your name", text: $name)
                    TextField("Special instructions", text: $notes, axis: .vertical)
                    Picker("Tip", selection: $tipPercent) {
                        Text("No tip").tag(0)
                        Text("10%").tag(10)
                        Text("15%").tag(15)
                        Text("20%").tag(20)
                    }
                }
                Section {
                    LabeledContent("Subtotal", value: money(subtotal))
                    LabeledContent("Tax", value: money(tax))
                    LabeledContent("Tip", value: money(tip))
                    LabeledContent("Total", value: money(total))
                        .font(.headline)
                }
                if let error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
                Section {
                    Button(placing ? "Placing…" : "Place order") {
                        Task { await place() }
                    }
                    .disabled(placing || cart.isEmpty)
                }
                if let placed {
                    Section("Pay") {
                        CheckoutView(order: placed) { paid in
                            onPlaced(paid)
                            dismiss()
                        }
                    }
                }
            }
            .navigationTitle("Order ahead")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
        }
    }

    private func money(_ cents: Int) -> String {
        String(format: "$%.2f", Double(cents) / 100)
    }

    private func place() async {
        placing = true
        error = nil
        defer { placing = false }
        let request = NewOrderRequest(
            truckId: truck.id.uuidString,
            customerUserId: nil,
            customerName: name.isEmpty ? nil : name,
            items: cart.map { NewOrderLineItem(menuItemId: $0.item.id, quantity: $0.quantity, modifiers: $0.modifiers) },
            specialInstructions: notes.isEmpty ? nil : notes,
            tipCents: tip
        )
        do {
            placed = try await api.createOrder(request)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

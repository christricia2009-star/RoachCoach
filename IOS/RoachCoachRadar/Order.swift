import Foundation

/// Matches backend/main.py's `OrderOut` / `OrderItemOut` (camelCase aliases,
/// same convention as Sighting.swift / MenuItem.swift).

enum OrderStatus: String, Codable, CaseIterable, Hashable {
    case pending, accepted, preparing, ready, completed, cancelled

    var displayName: String {
        switch self {
        case .pending: return "New"
        case .accepted: return "Accepted"
        case .preparing: return "Preparing"
        case .ready: return "Ready for Pickup"
        case .completed: return "Completed"
        case .cancelled: return "Cancelled"
        }
    }

    /// Next status an owner can advance an order to with one tap, in
    /// order. Empty for terminal states.
    var nextStatuses: [OrderStatus] {
        switch self {
        case .pending: return [.accepted, .cancelled]
        case .accepted: return [.preparing, .cancelled]
        case .preparing: return [.ready, .cancelled]
        case .ready: return [.completed]
        case .completed, .cancelled: return []
        }
    }
}

struct OrderLineItem: Identifiable, Codable, Hashable {
    var menuItemId: String?
    var nameSnapshot: String
    var unitPriceCents: Int
    var quantity: Int
    var modifiers: [MenuItemModifier]
    var lineTotalCents: Int

    var id: String { "\(menuItemId ?? nameSnapshot)-\(quantity)-\(lineTotalCents)" }

    enum CodingKeys: String, CodingKey {
        case menuItemId, nameSnapshot, unitPriceCents, quantity, modifiers, lineTotalCents
    }
}

struct Order: Identifiable, Codable, Hashable {
    let id: String
    var truckId: String
    var customerUserId: String?
    var customerName: String?
    var status: OrderStatus
    var items: [OrderLineItem]
    var subtotalCents: Int
    var taxCents: Int
    var tipCents: Int
    var totalCents: Int
    var currency: String
    var specialInstructions: String?
    var pickupEtaMinutes: Int?
    var paymentProvider: String?
    var paymentStatus: String
    var createdAt: Date
    var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, truckId, customerUserId, customerName, status, items
        case subtotalCents, taxCents, tipCents, totalCents, currency
        case specialInstructions, pickupEtaMinutes, paymentProvider, paymentStatus
        case createdAt, updatedAt
    }

    var totalDisplay: String {
        String(format: "$%.2f", Double(totalCents) / 100.0)
    }

    init(
        id: String,
        truckId: String,
        customerUserId: String? = nil,
        customerName: String? = nil,
        status: OrderStatus,
        items: [OrderLineItem],
        subtotalCents: Int,
        taxCents: Int,
        tipCents: Int,
        totalCents: Int,
        currency: String = "USD",
        specialInstructions: String? = nil,
        pickupEtaMinutes: Int? = nil,
        paymentProvider: String? = nil,
        paymentStatus: String = "unpaid",
        createdAt: Date,
        updatedAt: Date
    ) {
        self.id = id
        self.truckId = truckId
        self.customerUserId = customerUserId
        self.customerName = customerName
        self.status = status
        self.items = items
        self.subtotalCents = subtotalCents
        self.taxCents = taxCents
        self.tipCents = tipCents
        self.totalCents = totalCents
        self.currency = currency
        self.specialInstructions = specialInstructions
        self.pickupEtaMinutes = pickupEtaMinutes
        self.paymentProvider = paymentProvider
        self.paymentStatus = paymentStatus
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }
}

/// Client -> server payload for POST /api/orders. Server resolves prices
/// from the live MenuItem records — this only carries quantities/ids, never
/// prices, so a stale cached menu on-device can't under/over-charge.
struct NewOrderLineItem: Codable {
    var menuItemId: String
    var quantity: Int
    var modifiers: [MenuItemModifier]
}

struct NewOrderRequest: Codable {
    var truckId: String
    var customerUserId: String?
    var customerName: String?
    var items: [NewOrderLineItem]
    var specialInstructions: String?
    var tipCents: Int
}

// ============================================================
// PHASE 5: PAYMENTS
//
// Matches backend/payments.py + the PaymentIntentOut / PaymentResultOut
// wire formats in backend/main.py. See PaymentService.swift for how
// these get turned into an actual on-device charge.
// ============================================================

/// Returned by POST /api/orders/{id}/payments/stripe/intent. clientSecret
/// is handed to Stripe's PaymentSheet, never persisted or logged.
struct StripePaymentIntent: Codable {
    var provider: String
    var paymentIntentId: String
    var clientSecret: String
    var status: String
    var amountCents: Int
    var currency: String

    enum CodingKeys: String, CodingKey {
        case provider, paymentIntentId, clientSecret, status, amountCents, currency
    }
}

/// Client -> server payload for POST /api/orders/{id}/payments/square/charge.
/// sourceId is the one-time card nonce from Square's In-App Payments SDK
/// CardEntry flow — never a raw card number.
struct SquareChargeRequest: Codable {
    var sourceId: String
    var verificationToken: String?
}

/// Returned by both the Square charge endpoint and (for convenience)
/// usable wherever a payment attempt's resulting Order is needed.
struct PaymentResult: Codable {
    var provider: String
    var status: String
    var order: Order
}

/// Non-secret config from GET /api/payments/config — mirrors
/// backend/payments.py's public_config(). Lets the client decide which
/// payment sheet to present without hardcoding a provider.
struct PaymentsConfig: Codable {
    struct StripeConfig: Codable {
        var enabled: Bool
        var publishableKey: String?
    }
    struct SquareConfig: Codable {
        var enabled: Bool
        var applicationId: String?
        var locationId: String?
        var environment: String
    }

    var provider: String
    var stripe: StripeConfig
    var square: SquareConfig
}

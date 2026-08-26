import Foundation
import SwiftUI

#if canImport(StripePaymentSheet)
import StripePaymentSheet
#endif

/// Phase 5: on-device payment flow, paired with backend/payments.py.
///
/// Setup required once, in Xcode (not doable from source alone):
///   File > Add Package Dependencies… > https://github.com/stripe/stripe-ios
///   and add the "StripePaymentSheet" product to the RoachCoachRadar target.
///
/// Until that package is added, everything here still compiles — the
/// `#if canImport(StripePaymentSheet)` guards mean CheckoutView shows a
/// "payments not configured" placeholder instead of failing the build.
///
/// Square: the In-App Payments SDK (SQIPCardEntry) issues a one-time
/// `sourceId` nonce from a native card-entry screen, which is then sent
/// to POST /api/orders/{id}/payments/square/charge via
/// APIServicing.chargeSquare(...). It's a separate CocoaPod/SPM
/// ("square-in-app-payments-ios") from Stripe's; add it the same way if
/// Square is the chosen provider, then swap in SQIPCardEntryViewController
/// wherever `sourceId` is produced below.
@MainActor
final class PaymentService: ObservableObject {

    enum State: Equatable {
        case idle
        case loadingConfig
        case preparingIntent
        case ready
        case processing
        case succeeded(Order)
        case failed(String)
    }

    @Published private(set) var state: State = .idle
    @Published var config: PaymentsConfig?

    #if canImport(StripePaymentSheet)
    @Published var paymentSheet: PaymentSheet?
    #endif

    private let api: APIServicing

    init(api: APIServicing = LiveAPIService.shared) {
        self.api = api
    }

    /// Loads provider config, then (for Stripe) creates the PaymentIntent
    /// and builds a ready-to-present PaymentSheet for `order`.
    func prepare(for order: Order) async {
        state = .loadingConfig
        do {
            let cfg = try await api.fetchPaymentsConfig()
            config = cfg

            guard cfg.stripe.enabled, let publishableKey = cfg.stripe.publishableKey else {
                // Square (or nothing) configured — the caller is expected to
                // route to the Square card-entry flow instead of this sheet.
                state = .ready
                return
            }

            state = .preparingIntent
            let intent = try await api.createStripePaymentIntent(orderId: order.id)

            #if canImport(StripePaymentSheet)
            StripeAPI.defaultPublishableKey = publishableKey

            var configuration = PaymentSheet.Configuration()
            configuration.merchantDisplayName = "Roach Coach"
            configuration.allowsDelayedPaymentMethods = false

            paymentSheet = PaymentSheet(paymentIntentClientSecret: intent.clientSecret, configuration: configuration)
            #endif

            state = .ready
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    #if canImport(StripePaymentSheet)
    /// Presents the prepared PaymentSheet. Call from a SwiftUI view via
    /// `.paymentSheet(isPresented:paymentSheet:onCompletion:)` — this
    /// method just centralizes the result handling.
    func handle(_ result: PaymentSheetResult, order: Order) async {
        switch result {
        case .completed:
            // Stripe's webhook is the real source of truth for
            // paymentStatus; re-fetch so the UI reflects it without
            // racing the webhook by more than a request round-trip.
            state = .processing
            do {
                let refreshed = try await api.fetchOrder(id: order.id)
                state = .succeeded(refreshed)
            } catch {
                state = .succeeded(order) // sheet confirmed; treat as paid even if refresh failed
            }
        case .canceled:
            state = .ready
        case .failed(let error):
            state = .failed(error.localizedDescription)
        }
    }
    #endif

    /// Square path: caller obtains `sourceId` from SQIPCardEntryViewController
    /// (see file header) and passes it here.
    func chargeSquare(orderId: String, sourceId: String, verificationToken: String? = nil) async {
        state = .processing
        do {
            let result = try await api.chargeSquare(orderId: orderId, sourceId: sourceId, verificationToken: verificationToken)
            state = .succeeded(result.order)
        } catch {
            state = .failed(error.localizedDescription)
        }
    }
}

/// Drop-in checkout screen for the Order Ahead flow. Presents Stripe's
/// PaymentSheet when configured; otherwise shows a placeholder so the
/// app degrades gracefully rather than crashing on a missing SDK/config.
struct CheckoutView: View {
    let order: Order
    var onPaid: (Order) -> Void

    @StateObject private var service = PaymentService()
    @State private var presentingSheet = false

    var body: some View {
        VStack(spacing: 16) {
            Text("Pay for your order")
                .font(.headline)
            Text(order.totalDisplay)
                .font(.title2.bold())
                .foregroundStyle(.green)

            switch service.state {
            case .idle, .loadingConfig, .preparingIntent:
                ProgressView("Preparing payment…")

            case .ready:
                #if canImport(StripePaymentSheet)
                if let sheet = service.paymentSheet {
                    Button("Pay now") { presentingSheet = true }
                        .buttonStyle(.borderedProminent)
                        .paymentSheet(
                            isPresented: $presentingSheet,
                            paymentSheet: sheet,
                            onCompletion: { result in
                                Task {
                                    await service.handle(result, order: order)
                                    if case .succeeded(let paid) = service.state {
                                        onPaid(paid)
                                    }
                                }
                            }
                        )
                } else {
                    unconfiguredNotice
                }
                #else
                unconfiguredNotice
                #endif

            case .processing:
                ProgressView("Processing payment…")

            case .succeeded(let paidOrder):
                Label("Payment received", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .onAppear { onPaid(paidOrder) }

            case .failed(let message):
                VStack(spacing: 8) {
                    Text(message)
                        .foregroundStyle(.red)
                        .font(.footnote)
                    Button("Try again") {
                        Task { await service.prepare(for: order) }
                    }
                }
            }
        }
        .padding()
        .task { await service.prepare(for: order) }
    }

    private var unconfiguredNotice: some View {
        Text("No payment method is configured for this truck yet.")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
    }
}

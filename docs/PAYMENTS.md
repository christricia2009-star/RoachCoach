# Phase 5: Payments (Stripe + Square)

Adds real checkout to the Order Ahead flow that Phase 1 (menu/order models)
and Phase 2 (web map + live order tracking) built on top of. Orders are
always created **unpaid**; this phase adds the endpoints and client UI
that turn `paymentStatus` into `authorized`/`captured`.

## How it fits together

```
create order (unpaid) ──> customer pays ──> paymentStatus becomes captured
                             │
                 ┌───────────┴────────────┐
                 │                        │
              Stripe                    Square
      PaymentIntent + webhook     synchronous charge + webhook
```

- **Stripe**: client asks the backend for a `PaymentIntent`, confirms it
  client-side (Stripe.js `PaymentElement` on web, `PaymentSheet` on iOS),
  and the backend's webhook is the actual source of truth for
  `paymentStatus` — the client-side confirmation is just used to move the
  UI along without waiting on the webhook round trip.
- **Square**: the client tokenizes a card into a one-time `sourceId`
  nonce (Web Payments SDK on web, In-App Payments SDK on iOS) and the
  backend charges it synchronously — no webhook wait needed for the
  initial charge; Square's webhook only matters for later async events
  (refunds, disputes).

Both providers stay wired regardless of which is "primary" —
`PAYMENT_PROVIDER` in `.env` just picks the client's default when both
are configured (see `GET /api/payments/config`).

## Backend setup

1. `pip install -r backend/requirements.txt` (adds `stripe` and `squareup`).
2. Fill in `backend/.env` from `backend/.env.example`:
   - Stripe: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`
   - Square: `SQUARE_ACCESS_TOKEN`, `SQUARE_APPLICATION_ID`, `SQUARE_LOCATION_ID`, `SQUARE_WEBHOOK_SIGNATURE_KEY`, `SQUARE_ENVIRONMENT`
3. Register webhooks:
   - Stripe: point an endpoint at `POST /api/payments/stripe/webhook`,
     subscribed to `payment_intent.succeeded`, `payment_intent.payment_failed`,
     `payment_intent.processing`. In dev, use `stripe listen --forward-to
     localhost:8000/api/payments/stripe/webhook` and copy the CLI's
     signing secret into `STRIPE_WEBHOOK_SECRET`.
   - Square: point a webhook subscription at `POST
     /api/payments/square/webhook` for `payment.updated`, `refund.updated`.
     Square's signature covers the *exact* URL you registered — if that
     URL differs from what the deployed app sees (e.g. behind a proxy),
     signature verification will fail.
4. No new CloudKit record type is needed — `Order.paymentProvider`,
   `Order.paymentStatus`, and `Order.paymentIntentID` were already
   reserved by Phase 1 (see `cloudkit_schema.txt`); this phase just
   starts writing to them.

## Web setup

1. `npm install` (adds `@stripe/stripe-js` + `@stripe/react-stripe-js`;
   Square's Web Payments SDK loads as a `<script>` tag at runtime, see
   `app/lib/payments.js`, so it isn't an npm dependency).
2. Nothing else — `TruckDetail.js` already renders `<Checkout>` once an
   order is placed and unpaid, and `Checkout.js` reads
   `GET /api/payments/config` to decide what to show.

## iOS setup

1. In Xcode: **File > Add Package Dependencies…** →
   `https://github.com/stripe/stripe-ios` → add the **StripePaymentSheet**
   product to the RoachCoachRadar target.
2. For Square, add **square-in-app-payments-ios** the same way, and wire
   `SQIPCardEntryViewController` wherever `PaymentService.chargeSquare(...)`
   expects a `sourceId` (see the header comment in `PaymentService.swift`
   for exactly where).
3. That's it for wiring — this project uses Xcode's file-system-synchronized
   groups (`PBXFileSystemSynchronizedRootGroup`), so `PaymentService.swift`
   is already part of the target just by living in `IOS/RoachCoachRadar/`.
4. Until the Stripe package is added, the app still compiles:
   `PaymentService.swift` guards all Stripe usage behind `#if
   canImport(StripePaymentSheet)` and shows a "not configured" placeholder
   instead.

## Security notes

- The server **always** recomputes the charge amount from the order's
  stored `total_cents` — never from anything the client sends — for both
  providers.
- Card data never touches this backend directly. Stripe and Square's
  client SDKs tokenize it in the browser/app; the backend only ever
  sees a `client_secret`/`sourceId`/webhook event.
- Idempotency keys are derived from the order id (`order_{id}_intent`,
  `order_{id}_charge`, `order_{id}_refund`) so retried requests (e.g. a
  flaky connection on mobile) can't double-charge.

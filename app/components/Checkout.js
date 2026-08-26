"use client";

import { useEffect, useMemo, useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { fetchPaymentsConfig, loadSquareSdk } from "../lib/payments";

function centsToDollars(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

let stripePromise = null;
function getStripe(publishableKey) {
  if (!stripePromise) stripePromise = loadStripe(publishableKey);
  return stripePromise;
}

/**
 * Renders the payment step between "order placed (unpaid)" and the
 * order-tracking confirmation screen. Shown for any order whose
 * paymentStatus isn't already "captured".
 *
 * order: the OrderOut just returned by POST /api/orders
 * onPaid: called with the updated order once payment succeeds
 */
export default function Checkout({ order, onPaid }) {
  const [config, setConfig] = useState(null);
  const [configError, setConfigError] = useState(null);
  const [provider, setProvider] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchPaymentsConfig()
      .then((cfg) => {
        if (cancelled) return;
        setConfig(cfg);
        setProvider(cfg.provider === "square" && cfg.square.enabled ? "square" : "stripe");
      })
      .catch((err) => !cancelled && setConfigError(err.message || "Could not load payment options"));
    return () => {
      cancelled = true;
    };
  }, []);

  if (configError) {
    return <div className="rc-checkout-error">{configError}</div>;
  }

  if (!config || !provider) {
    return <div className="rc-checkout-loading">Loading payment options…</div>;
  }

  const bothAvailable = config.stripe.enabled && config.square.enabled;

  return (
    <section className="rc-checkout">
      <h3 className="rc-checkout__title">Pay for your order</h3>
      <div className="rc-checkout__amount">{centsToDollars(order.totalCents)} due</div>

      {bothAvailable && (
        <div className="rc-checkout-methods">
          <button
            className={`rc-checkout-method${provider === "stripe" ? " rc-checkout-method--active" : ""}`}
            onClick={() => setProvider("stripe")}
            type="button"
          >
            Card (Stripe)
          </button>
          <button
            className={`rc-checkout-method${provider === "square" ? " rc-checkout-method--active" : ""}`}
            onClick={() => setProvider("square")}
            type="button"
          >
            Card (Square)
          </button>
        </div>
      )}

      {provider === "stripe" && config.stripe.enabled && (
        <StripeCheckout order={order} publishableKey={config.stripe.publishableKey} onPaid={onPaid} />
      )}

      {provider === "square" && config.square.enabled && (
        <SquareCheckout order={order} squareConfig={config.square} onPaid={onPaid} />
      )}

      {!config.stripe.enabled && !config.square.enabled && (
        <div className="rc-checkout-error">
          No payment method is configured yet. Ask the truck owner to set up Stripe or Square.
        </div>
      )}
    </section>
  );
}

// ---------------- Stripe ----------------

function StripeCheckout({ order, publishableKey, onPaid }) {
  const [clientSecret, setClientSecret] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setClientSecret(null);

    fetch(`/api/orders/${encodeURIComponent(order.id)}/payments/stripe/intent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(async (res) => {
        if (!res.ok) {
          const detail = await res.json().catch(() => null);
          throw new Error(detail?.detail || `Could not start payment (${res.status})`);
        }
        return res.json();
      })
      .then((data) => !cancelled && setClientSecret(data.clientSecret))
      .catch((err) => !cancelled && setError(err.message || "Could not start payment"));

    return () => {
      cancelled = true;
    };
  }, [order.id]);

  const stripe = useMemo(() => (publishableKey ? getStripe(publishableKey) : null), [publishableKey]);

  if (!publishableKey) {
    return <div className="rc-checkout-error">Stripe publishable key is not configured.</div>;
  }
  if (error) {
    return <div className="rc-checkout-error">{error}</div>;
  }
  if (!clientSecret) {
    return <div className="rc-checkout-loading">Preparing payment…</div>;
  }

  return (
    <Elements
      stripe={stripe}
      options={{ clientSecret, appearance: { theme: "night", labels: "floating" } }}
    >
      <StripePaymentForm order={order} onPaid={onPaid} />
    </Elements>
  );
}

function StripePaymentForm({ order, onPaid }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!stripe || !elements) return;

    setSubmitting(true);
    setError(null);

    const { error: confirmError, paymentIntent } = await stripe.confirmPayment({
      elements,
      redirect: "if_required",
    });

    if (confirmError) {
      setError(confirmError.message || "Payment failed");
      setSubmitting(false);
      return;
    }

    if (paymentIntent && (paymentIntent.status === "succeeded" || paymentIntent.status === "processing")) {
      // Stripe's webhook is the source of truth for paymentStatus, but we
      // don't need to wait on it here — fetch the order once the intent
      // has cleared client-side so the UI can move on immediately.
      try {
        const res = await fetch(`/api/orders/${encodeURIComponent(order.id)}`, { cache: "no-store" });
        const updated = await res.json();
        onPaid(updated);
      } catch {
        onPaid({ ...order, paymentStatus: "authorized", paymentProvider: "stripe" });
      }
    } else {
      setError("Payment did not complete. Please try again.");
    }

    setSubmitting(false);
  }

  return (
    <form onSubmit={handleSubmit} className="rc-checkout-form">
      <PaymentElement />
      {error && <div className="rc-checkout-error">{error}</div>}
      <button className="rc-add-btn rc-pay-btn" disabled={!stripe || submitting} type="submit">
        {submitting ? "Processing…" : "Pay now"}
      </button>
    </form>
  );
}

// ---------------- Square ----------------

function SquareCheckout({ order, squareConfig, onPaid }) {
  const [card, setCard] = useState(null);
  const [ready, setReady] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let cardInstance = null;

    async function init() {
      try {
        const Square = await loadSquareSdk(squareConfig.environment);
        if (cancelled) return;

        const payments = Square.payments(squareConfig.applicationId, squareConfig.locationId);
        cardInstance = await payments.card();
        await cardInstance.attach("#rc-square-card-container");

        if (cancelled) {
          cardInstance.destroy();
          return;
        }
        setCard(cardInstance);
        setReady(true);
      } catch (err) {
        if (!cancelled) setError(err.message || "Could not load Square payment form");
      }
    }

    init();

    return () => {
      cancelled = true;
      if (cardInstance) cardInstance.destroy();
    };
  }, [squareConfig.applicationId, squareConfig.locationId, squareConfig.environment]);

  async function handlePay() {
    if (!card) return;
    setSubmitting(true);
    setError(null);

    try {
      const result = await card.tokenize();
      if (result.status !== "OK") {
        throw new Error(result.errors?.[0]?.message || "Card could not be verified");
      }

      const res = await fetch(`/api/orders/${encodeURIComponent(order.id)}/payments/square/charge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sourceId: result.token }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || `Payment failed (${res.status})`);
      }

      const data = await res.json();
      onPaid(data.order);
    } catch (err) {
      setError(err.message || "Payment failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rc-checkout-form">
      <div id="rc-square-card-container" className="rc-square-card" />
      {error && <div className="rc-checkout-error">{error}</div>}
      <button className="rc-add-btn rc-pay-btn" disabled={!ready || submitting} onClick={handlePay} type="button">
        {submitting ? "Processing…" : "Pay now"}
      </button>
    </div>
  );
}

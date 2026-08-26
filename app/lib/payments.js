// Phase 5: payments — shared helpers for the checkout step.
//
// Stripe ships an official npm SDK (@stripe/stripe-js), but Square's Web
// Payments SDK is only distributed as a hosted <script> (there's no
// supported npm build for the browser bundle), so it's loaded here the
// same way Square's own docs do it: inject the script tag once, cache
// the promise so repeated mounts of <Checkout> don't re-inject it.

let squareScriptPromise = null;

export function loadSquareSdk(environment) {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Square SDK can only load in the browser"));
  }
  if (window.Square) return Promise.resolve(window.Square);
  if (squareScriptPromise) return squareScriptPromise;

  const src =
    environment === "production"
      ? "https://web.squarecdn.com/v1/square.js"
      : "https://sandbox.web.squarecdn.com/v1/square.js";

  squareScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => (window.Square ? resolve(window.Square) : reject(new Error("Square SDK failed to load")));
    script.onerror = () => reject(new Error("Square SDK failed to load"));
    document.head.appendChild(script);
  });

  return squareScriptPromise;
}

export async function fetchPaymentsConfig() {
  const res = await fetch("/api/payments/config", { cache: "no-store" });
  if (!res.ok) throw new Error(`Could not load payment config (${res.status})`);
  return res.json();
}

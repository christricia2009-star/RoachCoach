"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Checkout from "../../components/Checkout";

const PAID = new Set(["authorized", "captured"]);

export default function PayOrderPage() {
  const params = useParams();
  const orderId = params?.orderId;
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!orderId) return;
    let cancelled = false;
    fetch(`/api/orders/${encodeURIComponent(orderId)}`, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail || `Order ${res.status}`);
        }
        return res.json();
      })
      .then((data) => {
        if (!cancelled) setOrder(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Order not found");
      });
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  if (error) {
    return (
      <div className="rc-detail-shell">
        <div className="rc-checkout-error">{error}</div>
        <Link href="/fleet">Back to fleet</Link>
      </div>
    );
  }

  if (!order) {
    return (
      <div className="rc-detail-shell">
        <div className="rc-detail-loading">Loading payment…</div>
      </div>
    );
  }

  if (PAID.has(order.paymentStatus)) {
    return (
      <div className="rc-detail-shell">
        <div className="rc-confirm">
          <h2>Payment received</h2>
          <p>Order #{String(order.id).slice(-8)} is paid.</p>
          {order.truckId && (
            <Link href={`/trucks/${encodeURIComponent(order.truckId)}`}>Back to truck</Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="rc-detail-shell">
      <Checkout order={order} onPaid={(updated) => setOrder(updated)} />
    </div>
  );
}

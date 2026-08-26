"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  notificationPermission,
  notificationsSupported,
  notify,
  requestNotificationPermission,
} from "../lib/notify";

const COLUMNS = [
  { status: "pending", label: "New", action: "accepted", actionLabel: "Accept" },
  { status: "accepted", label: "Accepted", action: "preparing", actionLabel: "Start preparing" },
  { status: "preparing", label: "Preparing", action: "ready", actionLabel: "Mark ready" },
  { status: "ready", label: "Ready for pickup", action: "completed", actionLabel: "Complete pickup" },
];

const POLL_MS = 6000;

function ownerHeaders(extra = {}) {
  const token = typeof window !== "undefined" ? sessionStorage.getItem("ownerToken") || "" : "";
  return {
    ...extra,
    ...(token ? { "X-Owner-Token": token } : {}),
  };
}

function centsToDollars(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

function timeAgo(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 1) return "just now";
  if (mins === 1) return "1 min ago";
  return `${mins} min ago`;
}

export default function OwnerOrderBoard({ truckId }) {
  const [truck, setTruck] = useState(null);
  const [orders, setOrders] = useState([]);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [busyOrderId, setBusyOrderId] = useState(null);
  const [etaDraft, setEtaDraft] = useState({}); // orderId -> string
  const [live, setLive] = useState(false); // true once the SSE stream is actually connected
  const [notifPermission, setNotifPermission] = useState(notificationPermission());

  const pollRef = useRef(null);
  const esRef = useRef(null);
  const knownOrderIdsRef = useRef(new Set());
  const firstLoadRef = useRef(true);

  function applyOrders(data) {
    // Notify on any order id we haven't seen before landing in "pending" —
    // that's a brand-new order that needs the owner's attention.
    if (!firstLoadRef.current) {
      for (const o of data) {
        if (o.status === "pending" && !knownOrderIdsRef.current.has(o.id)) {
          notify(`New order #${o.id.slice(-8)}`, {
            body: `${centsToDollars(o.totalCents)}${o.customerName ? ` · ${o.customerName}` : ""}`,
          });
        }
      }
    }
    knownOrderIdsRef.current = new Set(data.map((o) => o.id));
    firstLoadRef.current = false;
    setOrders(data);
    setLoadError(null);
  }

  async function loadActiveOnce() {
    try {
      const res = await fetch(`/api/trucks/${encodeURIComponent(truckId)}/orders?active_only=true`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`orders ${res.status}`);
      applyOrders(await res.json());
    } catch (err) {
      setLoadError(err.message || "Unable to reach order feed");
    }
  }

  // Fall back to fixed-interval polling if EventSource isn't available
  // or the stream keeps failing (e.g. a proxy that buffers/blocks SSE).
  function startPollingFallback() {
    if (pollRef.current) return;
    loadActiveOnce();
    pollRef.current = setInterval(loadActiveOnce, POLL_MS);
  }

  useEffect(() => {
    let cancelled = false;

    fetch("/api/trucks", { cache: "no-store" })
      .then((r) => r.json())
      .then((trucks) => {
        if (!cancelled) setTruck(trucks.find((t) => t.id === truckId) || null);
      })
      .catch(() => {});

    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      startPollingFallback();
      return () => cancelled = true;
    }

    const es = new EventSource(`/api/trucks/${encodeURIComponent(truckId)}/orders/stream?active_only=true`);
    esRef.current = es;

    es.onopen = () => !cancelled && setLive(true);
    es.onmessage = (e) => {
      if (cancelled) return;
      try {
        applyOrders(JSON.parse(e.data));
      } catch {
        // ignore a malformed frame, the next one will self-correct
      }
    };
    es.onerror = () => {
      if (cancelled) return;
      setLive(false);
      // EventSource retries the same URL on its own; if it's failing
      // repeatedly (e.g. blocked), keep the board usable via polling.
      startPollingFallback();
    };

    return () => {
      cancelled = true;
      es.close();
      esRef.current = null;
      clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [truckId]);

  async function enableNotifications() {
    const perm = await requestNotificationPermission();
    setNotifPermission(perm);
  }

  async function loadHistory() {
    try {
      const res = await fetch(`/api/trucks/${encodeURIComponent(truckId)}/orders?active_only=false`, {
        cache: "no-store",
      });
      if (!res.ok) return;
      const data = await res.json();
      setHistory(data.filter((o) => o.status === "completed" || o.status === "cancelled"));
    } catch {
      // best-effort
    }
  }

  function toggleHistory() {
    const next = !showHistory;
    setShowHistory(next);
    if (next) loadHistory();
  }

  async function advance(order, nextStatus) {
    setBusyOrderId(order.id);
    try {
      const body = { status: nextStatus };
      const etaRaw = etaDraft[order.id];
      if (nextStatus === "accepted" && etaRaw) {
        const n = parseInt(etaRaw, 10);
        if (Number.isFinite(n) && n > 0) body.pickupEtaMinutes = n;
      }

      const res = await fetch(`/api/orders/${encodeURIComponent(order.id)}/status`, {
        method: "PATCH",
        headers: ownerHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        if (res.status === 401) {
          const token = window.prompt("Owner token") || "";
          if (token) sessionStorage.setItem("ownerToken", token);
        }
        throw new Error(`status update failed (${res.status})`);
      }
      const updated = await res.json();

      setOrders((prev) => {
        if (nextStatus === "completed" || nextStatus === "cancelled") {
          return prev.filter((o) => o.id !== order.id);
        }
        return prev.map((o) => (o.id === order.id ? updated : o));
      });
    } catch (err) {
      setLoadError(err.message || "Could not update order");
    } finally {
      setBusyOrderId(null);
    }
  }

  function cancelOrder(order) {
    if (confirm(`Cancel order #${order.id.slice(-8)}? This can't be undone.`)) {
      advance(order, "cancelled");
    }
  }

  return (
    <div className="rc-owner-shell">
      <header className="rc-owner-header">
        <div>
          <Link href={`/trucks/${truckId}`} className="rc-back-link">Menu</Link>
          <h1>{truck ? truck.name : "Order board"}</h1>
        </div>
        <div className="rc-owner-header__right">
          <span className={`rc-pill ${live ? "rc-pill--ok" : "rc-pill--warn"}`}>
            {live ? "🟢 Live" : "🟡 Polling"}
          </span>
          {loadError && <span className="rc-pill rc-pill--error">🔴 {loadError}</span>}
          {notificationsSupported() && notifPermission !== "granted" && (
            <button className="rc-add-btn" onClick={enableNotifications}>
              🔔 Enable notifications
            </button>
          )}
          <button className="rc-add-btn" onClick={toggleHistory}>
            {showHistory ? "Hide history" : "Show history"}
          </button>
        </div>
      </header>

      <div className="rc-board">
        {COLUMNS.map((col) => {
          const colOrders = orders
            .filter((o) => o.status === col.status)
            .sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));

          return (
            <div key={col.status} className="rc-board-col">
              <div className="rc-board-col__header">
                <span>{col.label}</span>
                <span className="rc-board-col__count">{colOrders.length}</span>
              </div>

              {colOrders.length === 0 && <p className="rc-detail-empty">No orders</p>}

              {colOrders.map((order) => (
                <article key={order.id} className="rc-order-card">
                  <div className="rc-order-card__top">
                    <strong>#{order.id.slice(-8)}</strong>
                    <span className="rc-order-card__time">{timeAgo(order.createdAt)}</span>
                  </div>

                  {order.customerName && <div className="rc-order-card__customer">{order.customerName}</div>}

                  <ul className="rc-order-card__items">
                    {order.items.map((line, i) => (
                      <li key={i}>
                        {line.quantity}× {line.nameSnapshot}
                        {line.modifiers?.length > 0 && (
                          <span className="rc-order-card__mods"> ({line.modifiers.map((m) => m.name).join(", ")})</span>
                        )}
                      </li>
                    ))}
                  </ul>

                  {order.specialInstructions && (
                    <div className="rc-order-card__note">📝 {order.specialInstructions}</div>
                  )}

                  <div className="rc-order-card__total">{centsToDollars(order.totalCents)}</div>

                  {col.status === "pending" && (
                    <input
                      className="rc-order-card__eta"
                      type="number"
                      min="1"
                      placeholder="ETA min (optional)"
                      value={etaDraft[order.id] || ""}
                      onChange={(e) => setEtaDraft((prev) => ({ ...prev, [order.id]: e.target.value }))}
                    />
                  )}

                  <div className="rc-order-card__actions">
                    <button
                      className="rc-add-btn"
                      disabled={busyOrderId === order.id}
                      onClick={() => advance(order, col.action)}
                    >
                      {busyOrderId === order.id ? "Updating…" : col.actionLabel}
                    </button>
                    <button
                      className="rc-cancel-btn"
                      disabled={busyOrderId === order.id}
                      onClick={() => cancelOrder(order)}
                    >
                      Cancel
                    </button>
                  </div>
                </article>
              ))}
            </div>
          );
        })}
      </div>

      {showHistory && (
        <section className="rc-owner-history">
          <h2>History</h2>
          {history.length === 0 && <p className="rc-detail-empty">No completed or cancelled orders yet.</p>}
          {history.map((order) => (
            <div key={order.id} className="rc-history-row">
              <span>#{order.id.slice(-8)}</span>
              <span className={`rc-history-status rc-history-status--${order.status}`}>{order.status}</span>
              <span>{order.customerName || "—"}</span>
              <span>{centsToDollars(order.totalCents)}</span>
              <span>{timeAgo(order.updatedAt)}</span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

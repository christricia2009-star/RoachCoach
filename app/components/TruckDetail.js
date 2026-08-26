"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { notificationsSupported, notify, requestNotificationPermission, notificationPermission } from "../lib/notify";
import Checkout from "./Checkout";

const PAID_STATUSES = new Set(["authorized", "captured"]);

const ORDER_STEPS = ["pending", "accepted", "preparing", "ready", "completed"];
const STEP_LABEL = {
  pending: "Received",
  accepted: "Accepted",
  preparing: "Preparing",
  ready: "Ready for pickup",
  completed: "Picked up",
  cancelled: "Cancelled",
};
const TIP_PRESETS_PCT = [0, 10, 15, 20];

function centsToDollars(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

function lineKey(menuItemId, modifierNames) {
  return `${menuItemId}::${[...modifierNames].sort().join(",")}`;
}

export default function TruckDetail({ truckId }) {
  const [truck, setTruck] = useState(null);
  const [menu, setMenu] = useState([]);
  const [loadState, setLoadState] = useState("loading"); // loading | ready | error
  const [loadError, setLoadError] = useState(null);

  const [selectedModsByItem, setSelectedModsByItem] = useState({}); // itemId -> Set(modifierName)
  const [cart, setCart] = useState({}); // lineKey -> cart line

  const [cartOpen, setCartOpen] = useState(false);
  const [customerName, setCustomerName] = useState("");
  const [specialInstructions, setSpecialInstructions] = useState("");
  const [tipPct, setTipPct] = useState(15);
  const [customTip, setCustomTip] = useState("");

  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState(null);
  const [order, setOrder] = useState(null);

  const [orderLive, setOrderLive] = useState(false);
  const prevStatusRef = useRef(null);
  const pollRef = useRef(null);

  // Live order tracking: SSE stream, falling back to polling if it's
  // unavailable or keeps failing. Notifies on meaningful status changes
  // so the customer doesn't have to keep the tab in the foreground.
  useEffect(() => {
    if (!order?.id) return;
    if (order.status === "completed" || order.status === "cancelled") return;

    prevStatusRef.current = order.status;
    let cancelled = false;
    let es = null;

    function handleUpdate(updated) {
      if (updated.status !== prevStatusRef.current) {
        if (updated.status === "ready") {
          notify("Your order is ready! 🍽️", { body: `Order #${updated.id.slice(-8)} is ready for pickup.` });
        } else if (updated.status === "accepted") {
          notify("Order accepted", {
            body: updated.pickupEtaMinutes ? `Ready in about ${updated.pickupEtaMinutes} min.` : "The truck has your order.",
          });
        } else if (updated.status === "cancelled") {
          notify("Order cancelled", { body: `Order #${updated.id.slice(-8)} was cancelled.` });
        }
        prevStatusRef.current = updated.status;
      }
      setOrder(updated);
    }

    function startPollingFallback() {
      if (pollRef.current) return;
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`/api/orders/${encodeURIComponent(order.id)}`, { cache: "no-store" });
          if (!res.ok) return;
          handleUpdate(await res.json());
        } catch {
          // transient network hiccup — next poll will retry
        }
      }, 5000);
    }

    if (typeof window !== "undefined" && typeof window.EventSource !== "undefined") {
      es = new EventSource(`/api/orders/${encodeURIComponent(order.id)}/stream`);
      es.onopen = () => !cancelled && setOrderLive(true);
      es.onmessage = (e) => {
        if (cancelled) return;
        try {
          handleUpdate(JSON.parse(e.data));
        } catch {
          // ignore a malformed frame, the next one will self-correct
        }
      };
      es.onerror = () => {
        if (cancelled) return;
        setOrderLive(false);
        startPollingFallback();
      };
    } else {
      startPollingFallback();
    }

    return () => {
      cancelled = true;
      es?.close();
      clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [order?.id]);

  // Load truck (no single-truck GET endpoint yet, so filter the list) + menu.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [trucksRes, menuRes] = await Promise.all([
          fetch("/api/trucks", { cache: "no-store" }),
          fetch(`/api/trucks/${encodeURIComponent(truckId)}/menu?available_only=true`, {
            cache: "no-store",
          }),
        ]);
        if (!trucksRes.ok) throw new Error(`trucks ${trucksRes.status}`);
        if (!menuRes.ok) throw new Error(`menu ${menuRes.status}`);

        const trucks = await trucksRes.json();
        const items = await menuRes.json();
        if (cancelled) return;

        const found = trucks.find((t) => t.id === truckId) || null;
        setTruck(found);
        setMenu(items.filter((i) => i.isAvailable !== false).sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0)));
        setLoadState("ready");
      } catch (err) {
        if (!cancelled) {
          setLoadError(err.message || "Unable to load truck");
          setLoadState("error");
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [truckId]);

  function toggleModifier(itemId, modName) {
    setSelectedModsByItem((prev) => {
      const current = new Set(prev[itemId] || []);
      if (current.has(modName)) current.delete(modName);
      else current.add(modName);
      return { ...prev, [itemId]: current };
    });
  }

  function addToCart(item) {
    const selectedNames = Array.from(selectedModsByItem[item.id] || []);
    const selectedModifiers = (item.modifiers || []).filter((m) => selectedNames.includes(m.name));
    const key = lineKey(item.id, selectedNames);

    setCart((prev) => {
      const existing = prev[key];
      const unitPriceCents =
        item.priceCents + selectedModifiers.reduce((sum, m) => sum + (m.priceDeltaCents || 0), 0);
      return {
        ...prev,
        [key]: {
          menuItemId: item.id,
          name: item.name,
          unitPriceCents,
          modifiers: selectedModifiers,
          quantity: (existing?.quantity || 0) + 1,
        },
      };
    });
    setCartOpen(true);
  }

  function changeQty(key, delta) {
    setCart((prev) => {
      const line = prev[key];
      if (!line) return prev;
      const nextQty = line.quantity + delta;
      if (nextQty <= 0) {
        const { [key]: _drop, ...rest } = prev;
        return rest;
      }
      return { ...prev, [key]: { ...line, quantity: nextQty } };
    });
  }

  const cartLines = Object.entries(cart);
  const itemCount = cartLines.reduce((sum, [, l]) => sum + l.quantity, 0);
  const subtotalCents = cartLines.reduce((sum, [, l]) => sum + l.unitPriceCents * l.quantity, 0);
  const tipCents = useMemo(() => {
    if (customTip !== "") {
      const n = Math.round(parseFloat(customTip) * 100);
      return Number.isFinite(n) && n >= 0 ? n : 0;
    }
    return Math.round((subtotalCents * tipPct) / 100);
  }, [customTip, tipPct, subtotalCents]);

  async function placeOrder() {
    setPlacing(true);
    setPlaceError(null);
    try {
      const payload = {
        truckId,
        customerName: customerName || undefined,
        items: cartLines.map(([, l]) => ({
          menuItemId: l.menuItemId,
          quantity: l.quantity,
          modifiers: l.modifiers,
        })),
        specialInstructions: specialInstructions || undefined,
        tipCents,
      };

      const res = await fetch("/api/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || `Order failed (${res.status})`);
      }

      const created = await res.json();
      setOrder(created);
      setCart({});
    } catch (err) {
      setPlaceError(err.message || "Could not place order");
    } finally {
      setPlacing(false);
    }
  }

  function startNewOrder() {
    setOrder(null);
    setPlaceError(null);
    setCustomerName("");
    setSpecialInstructions("");
    setTipPct(15);
    setCustomTip("");
  }

  if (loadState === "loading") {
    return (
      <div className="rc-detail-shell">
        <div className="rc-detail-loading">Loading truck…</div>
      </div>
    );
  }

  if (loadState === "error" || !truck) {
    return (
      <div className="rc-detail-shell">
        <Link href="/" className="rc-back-link">← Back to radar</Link>
        <div className="rc-pill rc-pill--error" style={{ marginTop: 16 }}>
          🔴 {loadError || "Truck not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="rc-detail-shell">
      <div className="rc-detail-topnav">
        <Link href="/" className="rc-back-link">← Back to radar</Link>
        <Link href={`/trucks/${truckId}/owner`} className="rc-back-link">Owner? Manage orders →</Link>
      </div>

      <header className="rc-detail-header">
        {truck.image_url && <img className="rc-detail-photo" src={truck.image_url} alt={truck.name} />}
        <div>
          <h1>{truck.name}</h1>
          {truck.cuisine_type && <p className="rc-detail-cuisine">{truck.cuisine_type}</p>}
          {truck.menu_highlights?.length > 0 && (
            <p className="rc-detail-highlights">✨ {truck.menu_highlights.join(" · ")}</p>
          )}
        </div>
      </header>

      {order ? (
        PAID_STATUSES.has(order.paymentStatus) ? (
          <OrderConfirmation order={order} onStartNew={startNewOrder} live={orderLive} />
        ) : (
          <Checkout order={order} onPaid={(updated) => setOrder(updated)} />
        )
      ) : (
        <>
          <section className="rc-menu">
            {menu.length === 0 && <p className="rc-detail-empty">No menu items available right now.</p>}
            {menu.map((item) => (
              <MenuItemCard
                key={item.id}
                item={item}
                selectedMods={selectedModsByItem[item.id] || new Set()}
                onToggleModifier={(modName) => toggleModifier(item.id, modName)}
                onAdd={() => addToCart(item)}
              />
            ))}
          </section>

          {itemCount > 0 && (
            <button className="rc-cart-fab" onClick={() => setCartOpen(true)}>
              🛒 {itemCount} item{itemCount === 1 ? "" : "s"} · {centsToDollars(subtotalCents)}
            </button>
          )}

          {cartOpen && (
            <CartPanel
              cartLines={cartLines}
              subtotalCents={subtotalCents}
              tipCents={tipCents}
              tipPct={tipPct}
              customTip={customTip}
              onTipPct={(pct) => {
                setTipPct(pct);
                setCustomTip("");
              }}
              onCustomTip={setCustomTip}
              customerName={customerName}
              onCustomerName={setCustomerName}
              specialInstructions={specialInstructions}
              onSpecialInstructions={setSpecialInstructions}
              onChangeQty={changeQty}
              onClose={() => setCartOpen(false)}
              onPlaceOrder={placeOrder}
              placing={placing}
              placeError={placeError}
            />
          )}
        </>
      )}
    </div>
  );
}

function MenuItemCard({ item, selectedMods, onToggleModifier, onAdd }) {
  return (
    <article className="rc-item-card">
      {item.photoURL && <img className="rc-item-photo" src={item.photoURL} alt={item.name} />}
      <div className="rc-item-body">
        <div className="rc-item-top">
          <h3>{item.name}</h3>
          <span className="rc-item-price">{centsToDollars(item.priceCents)}</span>
        </div>
        {item.description && <p className="rc-item-desc">{item.description}</p>}

        {item.modifiers?.length > 0 && (
          <div className="rc-item-mods">
            {item.modifiers.map((m) => (
              <button
                key={m.name}
                type="button"
                className={`rc-chip${selectedMods.has(m.name) ? " rc-chip--active" : ""}`}
                onClick={() => onToggleModifier(m.name)}
              >
                {m.name}
                {m.priceDeltaCents ? ` +${centsToDollars(m.priceDeltaCents)}` : ""}
              </button>
            ))}
          </div>
        )}

        <button className="rc-add-btn" onClick={onAdd}>Add to order</button>
      </div>
    </article>
  );
}

function CartPanel({
  cartLines,
  subtotalCents,
  tipCents,
  tipPct,
  customTip,
  onTipPct,
  onCustomTip,
  customerName,
  onCustomerName,
  specialInstructions,
  onSpecialInstructions,
  onChangeQty,
  onClose,
  onPlaceOrder,
  placing,
  placeError,
}) {
  const totalCents = subtotalCents + tipCents; // tax is resolved + added server-side

  return (
    <div className="rc-cart-overlay" onClick={onClose}>
      <div className="rc-cart-panel" onClick={(e) => e.stopPropagation()}>
        <div className="rc-cart-header">
          <h2>Your order</h2>
          <button className="rc-cart-close" onClick={onClose} aria-label="Close cart">✕</button>
        </div>

        <div className="rc-cart-lines">
          {cartLines.length === 0 && <p className="rc-detail-empty">Your cart is empty.</p>}
          {cartLines.map(([key, line]) => (
            <div key={key} className="rc-cart-line">
              <div>
                <div className="rc-cart-line__name">{line.name}</div>
                {line.modifiers.length > 0 && (
                  <div className="rc-cart-line__mods">{line.modifiers.map((m) => m.name).join(", ")}</div>
                )}
              </div>
              <div className="rc-cart-line__right">
                <div className="rc-qty">
                  <button onClick={() => onChangeQty(key, -1)}>−</button>
                  <span>{line.quantity}</span>
                  <button onClick={() => onChangeQty(key, 1)}>+</button>
                </div>
                <div className="rc-cart-line__price">{centsToDollars(line.unitPriceCents * line.quantity)}</div>
              </div>
            </div>
          ))}
        </div>

        {cartLines.length > 0 && (
          <>
            <label className="rc-field">
              Name for pickup (optional)
              <input value={customerName} onChange={(e) => onCustomerName(e.target.value)} placeholder="Jordan" />
            </label>

            <label className="rc-field">
              Special instructions (optional)
              <textarea
                value={specialInstructions}
                onChange={(e) => onSpecialInstructions(e.target.value)}
                placeholder="No cilantro, extra napkins…"
                rows={2}
              />
            </label>

            <div className="rc-field">
              Tip
              <div className="rc-tip-row">
                {TIP_PRESETS_PCT.map((pct) => (
                  <button
                    key={pct}
                    type="button"
                    className={`rc-chip${customTip === "" && tipPct === pct ? " rc-chip--active" : ""}`}
                    onClick={() => onTipPct(pct)}
                  >
                    {pct}%
                  </button>
                ))}
                <input
                  className="rc-tip-custom"
                  type="number"
                  min="0"
                  step="0.5"
                  placeholder="$ custom"
                  value={customTip}
                  onChange={(e) => onCustomTip(e.target.value)}
                />
              </div>
            </div>

            <div className="rc-cart-totals">
              <div><span>Subtotal</span><span>{centsToDollars(subtotalCents)}</span></div>
              <div><span>Tip</span><span>{centsToDollars(tipCents)}</span></div>
              <div className="rc-cart-totals__note">Tax is calculated server-side at checkout.</div>
              <div className="rc-cart-totals__total"><span>Estimated total</span><span>{centsToDollars(totalCents)}</span></div>
            </div>

            {placeError && <div className="rc-pill rc-pill--error" style={{ marginBottom: 10 }}>🔴 {placeError}</div>}

            <button className="rc-place-btn" onClick={onPlaceOrder} disabled={placing}>
              {placing ? "Placing order…" : `Place order · ${centsToDollars(totalCents)}`}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function OrderConfirmation({ order, onStartNew, live }) {
  const stepIndex = ORDER_STEPS.indexOf(order.status);
  const cancelled = order.status === "cancelled";
  const done = order.status === "completed" || cancelled;
  const [notifPermission, setNotifPermission] = useState(notificationPermission());

  return (
    <section className="rc-confirm">
      <div className="rc-confirm-top">
        <h2>Order placed 🎉</h2>
        {!done && (
          <span className={`rc-pill ${live ? "rc-pill--ok" : "rc-pill--warn"}`}>
            {live ? "🟢 Live" : "🟡 Polling"}
          </span>
        )}
      </div>
      <p className="rc-confirm-id">Order #{order.id.slice(-8)}</p>

      {!done && notificationsSupported() && notifPermission !== "granted" && (
        <button
          className="rc-add-btn"
          style={{ marginBottom: 14 }}
          onClick={async () => setNotifPermission(await requestNotificationPermission())}
        >
          🔔 Notify me when it's ready
        </button>
      )}

      {cancelled ? (
        <div className="rc-pill rc-pill--error">Order cancelled</div>
      ) : (
        <div className="rc-stepper">
          {ORDER_STEPS.map((step, i) => (
            <div key={step} className={`rc-step${i <= stepIndex ? " rc-step--done" : ""}`}>
              <span className="rc-step__dot" />
              <span className="rc-step__label">{STEP_LABEL[step]}</span>
            </div>
          ))}
        </div>
      )}

      {order.pickupEtaMinutes != null && !cancelled && (
        <p className="rc-confirm-eta">Ready in about {order.pickupEtaMinutes} min</p>
      )}

      <div className="rc-cart-lines">
        {order.items.map((line, i) => (
          <div key={i} className="rc-cart-line">
            <div>
              <div className="rc-cart-line__name">{line.quantity}× {line.nameSnapshot}</div>
              {line.modifiers?.length > 0 && (
                <div className="rc-cart-line__mods">{line.modifiers.map((m) => m.name).join(", ")}</div>
              )}
            </div>
            <div className="rc-cart-line__price">{centsToDollars(line.lineTotalCents)}</div>
          </div>
        ))}
      </div>

      <div className="rc-cart-totals">
        <div><span>Subtotal</span><span>{centsToDollars(order.subtotalCents)}</span></div>
        <div><span>Tax</span><span>{centsToDollars(order.taxCents)}</span></div>
        <div><span>Tip</span><span>{centsToDollars(order.tipCents)}</span></div>
        <div className="rc-cart-totals__total"><span>Total</span><span>{centsToDollars(order.totalCents)}</span></div>
      </div>

      <button className="rc-add-btn" onClick={onStartNew}>Start a new order</button>
    </section>
  );
}

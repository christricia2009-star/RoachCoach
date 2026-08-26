"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { REGION_ORDER, hasSocialPresence, truckRegion } from "../lib/trucks";
import TruckThumb from "./TruckThumb";

export default function TrucksList() {
  const [trucks, setTrucks] = useState([]);
  const [sightings, setSightings] = useState([]);
  const [search, setSearch] = useState("");
  const [region, setRegion] = useState("");
  const [cuisine, setCuisine] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [trucksRes, sightingsRes] = await Promise.all([
          fetch("/api/trucks", { cache: "no-store" }),
          fetch("/api/sightings", { cache: "no-store" }),
        ]);
        if (!trucksRes.ok) throw new Error(`trucks ${trucksRes.status}`);
        const truckRows = await trucksRes.json();
        const sightingRows = sightingsRes.ok ? await sightingsRes.json() : [];
        if (cancelled) return;
        setTrucks(Array.isArray(truckRows) ? truckRows : []);
        setSightings(Array.isArray(sightingRows) ? sightingRows : []);
        setLoadError(null);
      } catch (err) {
        if (!cancelled) setLoadError(err.message || "Unable to load trucks");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const listed = useMemo(() => trucks.filter(hasSocialPresence), [trucks]);

  const liveIds = useMemo(() => {
    const now = Date.now();
    const ids = new Set();
    for (const s of sightings) {
      const expires = s.expiresAt ? new Date(s.expiresAt).getTime() : null;
      if (expires !== null && expires < now) continue;
      const id = s.truckId ?? s.truck_id;
      if (id) ids.add(id);
    }
    return ids;
  }, [sightings]);

  const regions = useMemo(() => {
    const present = new Set(listed.map(truckRegion));
    return REGION_ORDER.filter((name) => present.has(name)).concat(
      [...present].filter((name) => !REGION_ORDER.includes(name)).sort()
    );
  }, [listed]);

  const cuisines = useMemo(
    () =>
      [...new Set(listed.map((t) => t.cuisine_type).filter(Boolean))].sort((a, b) =>
        a.localeCompare(b)
      ),
    [listed]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return listed
      .filter((truck) => {
        const hay = `${truck.name || ""} ${truck.cuisine_type || ""} ${truckRegion(truck)}`.toLowerCase();
        if (q && !hay.includes(q)) return false;
        if (region && truckRegion(truck) !== region) return false;
        if (cuisine && truck.cuisine_type !== cuisine) return false;
        return true;
      })
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }, [listed, search, region, cuisine]);

  const spotted = filtered.filter((t) => liveIds.has(t.id));
  const regionSections = useMemo(() => {
    const spottedIds = new Set(spotted.map((t) => t.id));
    const rest = filtered.filter((t) => !spottedIds.has(t.id));
    const groups = new Map();
    for (const truck of rest) {
      const key = truckRegion(truck);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(truck);
    }
    const order = regions.length ? regions : REGION_ORDER;
    return order.filter((name) => groups.has(name)).map((name) => ({ name, trucks: groups.get(name) }));
  }, [filtered, spotted, regions]);

  return (
    <div className="rc-fleet">
      <header className="rc-fleet-hero">
        <p className="rc-kicker">California fleet</p>
        <h1>Every truck we track.</h1>
        <p>Same directory as the app — Instagram/Facebook-backed, grouped by region, ready to order ahead.</p>
      </header>

      <div className="rc-hud-search rc-hud-search--wide">
        <span>Filter fleet</span>
        <input
          placeholder="Truck, cuisine, region"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="rc-hud-filters">
        <button type="button" className={!region ? "is-on" : ""} onClick={() => setRegion("")}>
          All sectors
        </button>
        {regions.map((name) => (
          <button key={name} type="button" className={region === name ? "is-on" : ""} onClick={() => setRegion(region === name ? "" : name)}>
            {name}
          </button>
        ))}
      </div>
      <div className="rc-hud-filters">
        <button type="button" className={!cuisine ? "is-on" : ""} onClick={() => setCuisine("")}>
          All cuisines
        </button>
        {cuisines.slice(0, 14).map((name) => (
          <button key={name} type="button" className={cuisine === name ? "is-on" : ""} onClick={() => setCuisine(cuisine === name ? "" : name)}>
            {name}
          </button>
        ))}
      </div>

      <div className="rc-fleet-count">
        {filtered.length} / {listed.length} trucks
      </div>

      {loading && <div className="rc-empty">Acquiring fleet…</div>}
      {loadError && <div className="rc-empty rc-empty--error">{loadError}</div>}

      {!loading && spotted.length > 0 && (
        <section className="rc-fleet-section">
          <h2>Spotted recently</h2>
          <div className="rc-fleet-grid">
            {spotted.map((truck) => (
              <TruckCard key={truck.id} truck={truck} live />
            ))}
          </div>
        </section>
      )}

      {regionSections.map((section) => (
        <section className="rc-fleet-section" key={section.name}>
          <h2>{section.name}</h2>
          <div className="rc-fleet-grid">
            {section.trucks.map((truck) => (
              <TruckCard key={truck.id} truck={truck} live={liveIds.has(truck.id)} />
            ))}
          </div>
        </section>
      ))}

      {!loading && !loadError && filtered.length === 0 && (
        <div className="rc-empty">No trucks in that sector.</div>
      )}
    </div>
  );
}

function TruckCard({ truck, live }) {
  return (
    <Link href={`/trucks/${encodeURIComponent(truck.id)}`} className="rc-fleet-card">
      <TruckThumb truck={truck} />
      <span>
        <strong>
          {truck.name}
          {live && <i className="rc-live-dot" />}
        </strong>
        <small>{[truck.cuisine_type, truckRegion(truck)].filter(Boolean).join(" · ")}</small>
      </span>
    </Link>
  );
}

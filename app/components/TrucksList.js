"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  REGION_ORDER,
  avatarUrl,
  hasSocialPresence,
  truckRegion,
} from "../lib/trucks";

function TruckThumb({ truck }) {
  const src = avatarUrl(truck);
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <span className="rc-thumb rc-thumb--fallback" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path
            fill="currentColor"
            d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5V9h2.2c.5 0 .96.24 1.25.64l1.9 2.6c.2.27.3.6.3.94V16a1.5 1.5 0 0 1-1.5 1.5h-.6a2.5 2.5 0 0 1-4.8 0h-4.4a2.5 2.5 0 0 1-4.8 0H3.5A1.5 1.5 0 0 1 2 16V7.5H3Z"
          />
        </svg>
      </span>
    );
  }
  return (
    <img
      className="rc-thumb"
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

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
    <div className="rc-trucks">
      <div className="rc-search-wrap">
        <span className="rc-search-icon" aria-hidden="true">
          ⌕
        </span>
        <input
          className="rc-ios-search"
          placeholder="Search trucks, cuisine, region"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button type="button" className="rc-search-clear" onClick={() => setSearch("")} aria-label="Clear search">
            ✕
          </button>
        )}
      </div>

      <div className="rc-chips" role="toolbar" aria-label="Filters">
        <button type="button" className={`rc-filter${region === "" ? " rc-filter--on" : ""}`} onClick={() => setRegion("")}>
          All regions
        </button>
        {regions.map((name) => (
          <button
            key={name}
            type="button"
            className={`rc-filter${region === name ? " rc-filter--on" : ""}`}
            onClick={() => setRegion(region === name ? "" : name)}
          >
            {name}
          </button>
        ))}
      </div>
      {cuisines.length > 0 && (
        <div className="rc-chips" role="toolbar" aria-label="Cuisines">
          <button type="button" className={`rc-filter${cuisine === "" ? " rc-filter--on" : ""}`} onClick={() => setCuisine("")}>
            All cuisines
          </button>
          {cuisines.slice(0, 16).map((name) => (
            <button
              key={name}
              type="button"
              className={`rc-filter${cuisine === name ? " rc-filter--on" : ""}`}
              onClick={() => setCuisine(cuisine === name ? "" : name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      <div className="rc-count">{listed.length} trucks</div>

      {loading && <div className="rc-empty">Loading trucks…</div>}
      {loadError && <div className="rc-empty rc-empty--error">{loadError}</div>}

      {!loading && !loadError && spotted.length > 0 && (
        <section className="rc-group">
          <h2>Spotted Recently</h2>
          <div className="rc-card">
            {spotted.map((truck) => (
              <TruckRow key={truck.id} truck={truck} live />
            ))}
          </div>
        </section>
      )}

      {regionSections.map((section) => (
        <section className="rc-group" key={section.name}>
          <h2>{section.name}</h2>
          <div className="rc-card">
            {section.trucks.map((truck) => (
              <TruckRow key={truck.id} truck={truck} live={liveIds.has(truck.id)} />
            ))}
          </div>
        </section>
      ))}

      {!loading && !loadError && filtered.length === 0 && (
        <div className="rc-empty">No trucks match that search.</div>
      )}
    </div>
  );
}

function TruckRow({ truck, live }) {
  return (
    <Link href={`/trucks/${encodeURIComponent(truck.id)}`} className="rc-row">
      <TruckThumb truck={truck} />
      <span className="rc-row__body">
        <span className="rc-row__name">
          {truck.name}
          {live && <span className="rc-live-dot" title="Spotted recently" />}
        </span>
        <span className="rc-row__meta">
          {[truck.cuisine_type, truckRegion(truck)].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="rc-chevron" aria-hidden="true">
        ›
      </span>
    </Link>
  );
}

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import "maplibre-gl/dist/maplibre-gl.css";
import { avatarUrl, hasSocialPresence, truckRegion } from "../lib/trucks";

const DEFAULT_CENTER = [-121.4944, 38.5816];
const DEFAULT_ZOOM = 10;
const CA_BOUNDS = [
  [-124.5, 32.5],
  [-114.1, 42.1],
];

const DARK_STYLE = {
  version: 8,
  sources: {
    "carto-dark": {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
      ],
      tileSize: 256,
      attribution:
        "© <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> © <a href='https://carto.com/attributions'>CARTO</a>",
    },
  },
  layers: [{ id: "carto-dark-layer", type: "raster", source: "carto-dark" }],
};

const CONFIDENCE_COLOR = {
  high: "#3ee0c5",
  confirmed: "#3ee0c5",
  medium: "#ff7a1a",
  likely: "#ff7a1a",
  low: "#ff4d6a",
  possible: "#ff4d6a",
};

function nid(value) {
  return String(value || "").toLowerCase();
}

function escapeHtml(str) {
  return String(str ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function confidenceTone(level) {
  return CONFIDENCE_COLOR[String(level || "").toLowerCase()] || CONFIDENCE_COLOR.medium;
}

function relativeTime(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export default function CommandCenter() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const [contacts, setContacts] = useState([]);
  const [allTrucks, setAllTrucks] = useState([]);
  const [search, setSearch] = useState("");
  const [region, setRegion] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let observer;
    let map;

    (async () => {
      const maplibregl = (await import("maplibre-gl")).default;
      if (cancelled || !containerRef.current) return;

      map = new maplibregl.Map({
        container: containerRef.current,
        style: DARK_STYLE,
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
        attributionControl: true,
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
      map.addControl(
        new maplibregl.GeolocateControl({
          positionOptions: { enableHighAccuracy: true },
          trackUserLocation: true,
        }),
        "bottom-right"
      );

      const resize = () => {
        if (!map) return;
        map.resize();
      };
      map.on("load", () => {
        resize();
        if (!cancelled) setMapReady(true);
      });
      observer = new ResizeObserver(resize);
      observer.observe(containerRef.current);
      requestAnimationFrame(resize);
      setTimeout(resize, 250);
      mapRef.current = map;
    })();

    return () => {
      cancelled = true;
      observer?.disconnect();
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [trucksRes, sightingsRes] = await Promise.all([
          fetch("/api/trucks", { cache: "no-store" }),
          fetch("/api/sightings", { cache: "no-store" }),
        ]);
        if (!trucksRes.ok) throw new Error(`trucks ${trucksRes.status}`);
        const trucks = await trucksRes.json();
        const sightings = sightingsRes.ok ? await sightingsRes.json() : [];
        if (cancelled) return;

        const list = Array.isArray(trucks) ? trucks : [];
        setAllTrucks(list);
        const trucksById = new Map(list.map((t) => [nid(t.id), t]));

        const latestByTruck = new Map();
        for (const s of Array.isArray(sightings) ? sightings : []) {
          const lat = Number(s.latitude);
          const lng = Number(s.longitude);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
          const truckId = nid(s.truckId ?? s.truck_id);
          const ts = new Date(s.timestamp || 0).getTime();
          const key = truckId || s.id;
          const prev = latestByTruck.get(key);
          if (!prev || ts > prev._ts) {
            latestByTruck.set(key, { ...s, truckId, _ts: ts, latitude: lat, longitude: lng });
          }
        }

        const now = Date.now();
        const merged = [];
        for (const sighting of latestByTruck.values()) {
          const expiresAt = sighting.expiresAt ? new Date(sighting.expiresAt).getTime() : null;
          const isExpired = expiresAt !== null && expiresAt < now;
          const age = now - sighting._ts;
          merged.push({
            truck: trucksById.get(sighting.truckId) || null,
            sighting,
            isLive: !isExpired && age <= 3 * 60 * 60 * 1000,
            isStale: isExpired || age > 3 * 60 * 60 * 1000,
          });
        }
        merged.sort((a, b) => b.sighting._ts - a.sighting._ts);
        setContacts(merged);
        setLastUpdated(new Date());
        setLoadError(null);
      } catch (err) {
        if (!cancelled) setLoadError(err.message || "Radar backend unreachable");
      }
    }

    load();
    const interval = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const q = search.trim().toLowerCase();
  const visible = useMemo(() => {
    return contacts.filter(({ truck, sighting }) => {
      const cuisine = truck?.cuisine_type || "";
      const name = truck?.name || sighting.note || "";
      const hay = `${name} ${cuisine} ${truckRegion(truck || {})}`.toLowerCase();
      if (q && !hay.includes(q)) return false;
      if (region && truckRegion(truck || {}) !== region) return false;
      return true;
    });
  }, [contacts, q, region]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    let cancelled = false;

    (async () => {
      const maplibregl = (await import("maplibre-gl")).default;
      if (cancelled || !mapRef.current) return;
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];

      visible.forEach(({ truck, sighting, isLive }) => {
        const color = confidenceTone(sighting.confidenceLevel);
        const el = document.createElement("div");
        el.className = `rc-marker${isLive ? " rc-marker--live" : " rc-marker--ghost"}`;
        el.style.setProperty("--rc-color", color);
        el.innerHTML =
          `<span class="rc-marker__ring"></span><span class="rc-marker__core"></span>`;

        const name = truck?.name || sighting.note || "Unmatched ping";
        const popupHtml = `
          <div class="rc-popup">
            <strong>${escapeHtml(name)}</strong>
            <div class="rc-popup__meta">${escapeHtml(truck?.cuisine_type || "Signal contact")}</div>
            <div class="rc-popup__conf" style="color:${color}">
              ${escapeHtml(String(sighting.confidenceLevel || "likely"))} · ${isLive ? "active" : "last known"}
            </div>
            ${sighting.note ? `<div class="rc-popup__note">${escapeHtml(sighting.note)}</div>` : ""}
            ${truck?.id ? `<a class="rc-popup__link" href="/trucks/${encodeURIComponent(truck.id)}">Open truck →</a>` : ""}
          </div>
        `;

        const marker = new maplibregl.Marker({ element: el, anchor: "center" })
          .setLngLat([sighting.longitude, sighting.latitude])
          .setPopup(new maplibregl.Popup({ offset: 18, closeButton: false }).setHTML(popupHtml))
          .addTo(mapRef.current);
        markersRef.current.push(marker);
      });

      if (visible.length === 1) {
        mapRef.current.easeTo({
          center: [visible[0].sighting.longitude, visible[0].sighting.latitude],
          zoom: 12,
          duration: 600,
        });
      } else if (visible.length > 1) {
        const bounds = new maplibregl.LngLatBounds();
        visible.forEach(({ sighting }) => bounds.extend([sighting.longitude, sighting.latitude]));
        mapRef.current.fitBounds(bounds, { padding: 80, maxZoom: 12, duration: 600 });
      } else {
        mapRef.current.fitBounds(CA_BOUNDS, { padding: 24, duration: 400 });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [visible, mapReady]);

  const regions = useMemo(() => {
    const set = new Set(allTrucks.map(truckRegion).filter((r) => r && r !== "Other"));
    return ["Sacramento", "Bay Area", "North State", "Sierra", "Central Valley", "Central Coast"].filter((r) =>
      set.has(r)
    );
  }, [allTrucks]);

  const liveCount = visible.filter((c) => c.isLive).length;
  const fleet = allTrucks.filter(hasSocialPresence);
  const filteredFleet = fleet.filter((truck) => {
    const hay = `${truck.name} ${truck.cuisine_type || ""} ${truckRegion(truck)}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (region && truckRegion(truck) !== region) return false;
    return true;
  });

  return (
    <section className="rc-stage">
      <div className="rc-map-wrap">
        <div ref={containerRef} className="rc-map" />
        <div className="rc-scan" aria-hidden="true" />
        {!loadError && visible.length === 0 && (
          <div className="rc-map-empty">
            <span className="rc-kicker">No live pings</span>
            <strong>Map is up. Waiting on Instagram / check-ins.</strong>
            <p>Fleet is still searchable in the panel — pins appear when a truck is spotted.</p>
          </div>
        )}
      </div>

      <aside className="rc-hud">
        <div className="rc-hud__top">
          <div className="rc-stats">
            <div>
              <span className="rc-kicker">Live contacts</span>
              <strong>{liveCount.toString().padStart(2, "0")}</strong>
            </div>
            <div>
              <span className="rc-kicker">Pins</span>
              <strong>{visible.length.toString().padStart(2, "0")}</strong>
            </div>
            <div>
              <span className="rc-kicker">Fleet</span>
              <strong>{fleet.length}</strong>
            </div>
          </div>
          <label className="rc-hud-search">
            <span>Search signal</span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Truck, cuisine, region"
            />
          </label>
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
          {loadError && <div className="rc-hud-error">{loadError}</div>}
          {lastUpdated && (
            <div className="rc-hud-stamp">
              Sweep {lastUpdated.toLocaleTimeString()} · refresh 30s
            </div>
          )}
        </div>

        <div className="rc-hud__list">
          <div className="rc-kicker">Active radar</div>
          {visible.length === 0 && <p className="rc-hud-empty">No mapped contacts yet.</p>}
          {visible.slice(0, 12).map(({ truck, sighting, isLive }) => (
            <Link
              key={sighting.id || sighting.truckId}
              href={truck?.id ? `/trucks/${encodeURIComponent(truck.id)}` : "/fleet"}
              className="rc-contact"
            >
              <span className={`rc-contact__pulse${isLive ? " is-live" : ""}`} />
              <span className="rc-contact__body">
                <strong>{truck?.name || "Unmatched ping"}</strong>
                <small>
                  {truck?.cuisine_type || "Unknown cuisine"} · {relativeTime(sighting.timestamp)}
                </small>
              </span>
            </Link>
          ))}

          <div className="rc-kicker rc-kicker--gap">Fleet</div>
          {filteredFleet.slice(0, 18).map((truck) => (
            <Link key={truck.id} href={`/trucks/${encodeURIComponent(truck.id)}`} className="rc-contact rc-contact--fleet">
              <img
                src={avatarUrl(truck)}
                alt=""
                onError={(e) => {
                  e.currentTarget.style.visibility = "hidden";
                }}
              />
              <span className="rc-contact__body">
                <strong>{truck.name}</strong>
                <small>
                  {[truck.cuisine_type, truckRegion(truck)].filter(Boolean).join(" · ")}
                </small>
              </span>
            </Link>
          ))}
          <Link href="/fleet" className="rc-hud-more">
            Open full fleet →
          </Link>
        </div>
      </aside>
    </section>
  );
}

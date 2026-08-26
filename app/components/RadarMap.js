"use client";

import { useEffect, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";

// Sacramento — matches backend/data/sacramento_trucks.json seed data.
const DEFAULT_CENTER = [-121.4944, 38.5816];
const DEFAULT_ZOOM = 11;

// No API key needed: CARTO's dark basemap is free for this kind of use
// and fits the existing #070b12 theme in globals.css.
const DARK_STYLE = {
  version: 8,
  sources: {
    "carto-dark": {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      ],
      tileSize: 256,
      attribution:
        "© <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors © <a href='https://carto.com/attributions'>CARTO</a>",
    },
  },
  layers: [
    {
      id: "carto-dark-layer",
      type: "raster",
      source: "carto-dark",
      minzoom: 0,
      maxzoom: 20,
    },
  ],
};

const CONFIDENCE_COLOR = {
  high: "#9ee7b4",
  medium: "#f4d35e",
  low: "#f28a8a",
};

const ACTIVE_WINDOW_MS = 30 * 60 * 1000; // pulsing "live" radar contact
const RECENT_WINDOW_MS = 3 * 60 * 60 * 1000; // dim "last seen" ghost

function escapeHtml(str) {
  return String(str ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

export default function RadarMap() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const [contacts, setContacts] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Init map once.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const maplibregl = (await import("maplibre-gl")).default;
      if (cancelled || !containerRef.current) return;

      const map = new maplibregl.Map({
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

      mapRef.current = map;
    })();

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  // Fetch trucks + sightings, merge into radar "contacts" (one per truck:
  // its most recent, not-yet-expired sighting), same convention the iOS
  // MapContentView uses — a truck's location IS its latest sighting.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [trucksRes, sightingsRes] = await Promise.all([
          fetch("/api/trucks", { cache: "no-store" }),
          fetch("/api/sightings", { cache: "no-store" }),
        ]);
        if (!trucksRes.ok) throw new Error(`trucks ${trucksRes.status}`);
        if (!sightingsRes.ok) throw new Error(`sightings ${sightingsRes.status}`);

        const trucks = await trucksRes.json();
        const sightings = await sightingsRes.json();
        if (cancelled) return;

        const trucksById = new Map(trucks.map((t) => [t.id, t]));
        const latestByTruck = new Map();

        for (const s of sightings) {
          const truckId = s.truckId ?? s.truck_id;
          if (!truckId || !trucksById.has(truckId)) continue;
          const ts = new Date(s.timestamp).getTime();
          const prev = latestByTruck.get(truckId);
          if (!prev || ts > prev._ts) latestByTruck.set(truckId, { ...s, truckId, _ts: ts });
        }

        const now = Date.now();
        const merged = [];
        for (const [truckId, sighting] of latestByTruck) {
          const expiresAt = sighting.expiresAt ? new Date(sighting.expiresAt).getTime() : null;
          const isExpired = expiresAt !== null && expiresAt < now;
          const age = now - sighting._ts;
          if (isExpired && age > RECENT_WINDOW_MS) continue; // faded off radar entirely
          merged.push({
            truck: trucksById.get(truckId),
            sighting,
            isLive: !isExpired && age <= ACTIVE_WINDOW_MS,
          });
        }

        setContacts(merged);
        setLastUpdated(new Date());
        setLoadError(null);
      } catch (err) {
        if (!cancelled) setLoadError(err.message || "Unable to reach Radar backend");
      }
    }

    load();
    const interval = setInterval(load, 30_000); // radar "sweep" refresh
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Render markers whenever contacts change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    let raf = requestAnimationFrame(async function place() {
      if (!mapRef.current) return;
      const maplibregl = (await import("maplibre-gl")).default;

      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];

      contacts.forEach(({ truck, sighting, isLive }) => {
        const color = CONFIDENCE_COLOR[sighting.confidenceLevel] || CONFIDENCE_COLOR.medium;

        const el = document.createElement("div");
        el.className = `rc-marker${isLive ? " rc-marker--live" : " rc-marker--ghost"}`;
        el.style.setProperty("--rc-color", color);
        el.innerHTML = `<span class="rc-marker__pulse"></span><span class="rc-marker__dot">🪳</span>`;

        const popupHtml = `
          <div class="rc-popup">
            <strong>${escapeHtml(truck?.name || "Unknown truck")}</strong>
            <div class="rc-popup__meta">${escapeHtml(truck?.cuisine_type || "Cuisine unknown")}</div>
            <div class="rc-popup__conf" style="color:${color}">
              ${escapeHtml(sighting.confidenceLevel || "medium")} confidence · ${isLive ? "live" : "last seen"}
            </div>
            ${sighting.note ? `<div class="rc-popup__note">${escapeHtml(sighting.note)}</div>` : ""}
            <a class="rc-popup__link" href="/trucks/${encodeURIComponent(truck?.id || "")}">View menu &amp; order →</a>
          </div>
        `;

        const marker = new maplibregl.Marker({ element: el, anchor: "center" })
          .setLngLat([sighting.longitude, sighting.latitude])
          .setPopup(new maplibregl.Popup({ offset: 18, closeButton: false }).setHTML(popupHtml))
          .addTo(mapRef.current);

        markersRef.current.push(marker);
      });
    });

    return () => cancelAnimationFrame(raf);
  }, [contacts]);

  return (
    <div className="rc-map-wrap">
      <div ref={containerRef} className="rc-map" />

      <div className="rc-map-topbar">
        <div className="rc-map-brand">
          <span className="eyebrow">RCR • 27.515</span>
          <h1>🪳 Roach Coach Radar</h1>
        </div>
        <div className="rc-map-status">
          {loadError ? (
            <span className="rc-pill rc-pill--error">🔴 {loadError}</span>
          ) : (
            <span className="rc-pill rc-pill--ok">
              🟢 {contacts.length} truck{contacts.length === 1 ? "" : "s"} on radar
            </span>
          )}
        </div>
      </div>

      <div className="rc-map-legend">
        <div className="rc-legend__title">Radar confidence</div>
        <div><span className="rc-legend__swatch" style={{ background: CONFIDENCE_COLOR.high }} /> High</div>
        <div><span className="rc-legend__swatch" style={{ background: CONFIDENCE_COLOR.medium }} /> Medium</div>
        <div><span className="rc-legend__swatch" style={{ background: CONFIDENCE_COLOR.low }} /> Low</div>
        <div className="rc-legend__note">
          Pulsing = live sighting (last 30 min). Dim = last seen, up to 3 hrs ago.
        </div>
        {lastUpdated && (
          <div className="rc-legend__updated">Updated {lastUpdated.toLocaleTimeString()}</div>
        )}
      </div>
    </div>
  );
}

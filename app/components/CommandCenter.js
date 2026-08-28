"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import "leaflet/dist/leaflet.css";
import { REGION_ORDER, hasSocialPresence, matchesTruckSearch, truckRegion } from "../lib/trucks";
import TruckThumb from "./TruckThumb";

const DEFAULT_CENTER = [38.5816, -121.4944];
const DEFAULT_ZOOM = 10;

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
  const [mapError, setMapError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let observer;
    let map;
    let tries = 0;

    (async () => {
      try {
        const el = containerRef.current;
        if (!el) return;
        while (!cancelled && tries < 40 && (el.clientWidth < 40 || el.clientHeight < 40)) {
          tries += 1;
          await new Promise((r) => setTimeout(r, 50));
        }
        if (cancelled) return;
        const leaflet = await import("leaflet");
        const L = leaflet.default || leaflet;
        map = L.map(el, {
          zoomControl: true,
          attributionControl: true,
        }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>",
          maxZoom: 19,
        }).addTo(map);
        const resize = () => map.invalidateSize();
        observer = new ResizeObserver(resize);
        observer.observe(el);
        setTimeout(resize, 80);
        setTimeout(resize, 400);
        mapRef.current = map;
        if (!cancelled) setMapReady(true);
      } catch (err) {
        if (!cancelled) setMapError(err.message || "Map failed to start");
      }
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

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return contacts.filter(({ truck, sighting }) => {
      if (region && truckRegion(truck || {}) !== region) return false;
      if (!q) return true;
      if (truck && matchesTruckSearch(truck, search)) return true;
      const hay = `${sighting.note || ""} ${sighting.address || ""}`.toLowerCase();
      return q.split(/\s+/).every((token) => hay.includes(token));
    });
  }, [contacts, search, region]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    let cancelled = false;

    (async () => {
      const leaflet = await import("leaflet");
      const L = leaflet.default || leaflet;
      if (cancelled || !mapRef.current) return;
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];

      const latlngs = [];
      visible.forEach(({ truck, sighting, isLive }) => {
        const color = confidenceTone(sighting.confidenceLevel);
        const name = truck?.name || sighting.note || "Unmatched ping";
        const label = name.replace(/\s+/g, " ").trim().slice(0, 28);
        const icon = L.divIcon({
          className: "rc-leaflet-pin",
          iconSize: [0, 0],
          iconAnchor: [0, 0],
          html: `<div class="rc-pin${isLive ? " is-live" : ""}" style="--rc-color:${color}">
            <span class="rc-pin__name">${escapeHtml(label)}</span>
            <span class="rc-pin__needle"></span>
          </div>`,
        });
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
        const marker = L.marker([sighting.latitude, sighting.longitude], { icon })
          .bindPopup(popupHtml)
          .addTo(mapRef.current);
        markersRef.current.push(marker);
        latlngs.push([sighting.latitude, sighting.longitude]);
      });

      if (latlngs.length === 1) {
        mapRef.current.setView(latlngs[0], 12);
      } else if (latlngs.length > 1) {
        mapRef.current.fitBounds(latlngs, { padding: [60, 60], maxZoom: 12 });
      }
      mapRef.current.invalidateSize();
    })();

    return () => {
      cancelled = true;
    };
  }, [visible, mapReady]);

  const regions = useMemo(() => {
    const set = new Set(allTrucks.map(truckRegion).filter((r) => r && r !== "Other"));
    return REGION_ORDER.filter((r) => r !== "Other" && set.has(r));
  }, [allTrucks]);

  const liveCount = visible.filter((c) => c.isLive).length;
  const fleet = allTrucks.filter(hasSocialPresence);
  const filteredFleet = fleet.filter((truck) => {
    if (!matchesTruckSearch(truck, search)) return false;
    if (region && truckRegion(truck) !== region) return false;
    return true;
  });

  return (
    <section className="rc-stage">
      <div className="rc-map-wrap">
        <div ref={containerRef} className="rc-map" />
        {mapError && <div className="rc-map-empty"><strong>{mapError}</strong></div>}
        {!mapReady && !mapError && <div className="rc-map-boot">Initializing map…</div>}
        {!mapError && mapReady && visible.length === 0 && (
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
              placeholder="Name or city — Plumas Lake, Blue Tulip…"
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
              {truck ? <TruckThumb truck={truck} /> : <span className={`rc-contact__pulse${isLive ? " is-live" : ""}`} />}
              <span className="rc-contact__body">
                <strong>
                  {truck?.name || "Unmatched ping"}
                  {isLive && <i className="rc-live-dot" />}
                </strong>
                <small>
                  {truck?.cuisine_type || "Unknown cuisine"} · {relativeTime(sighting.timestamp)}
                </small>
              </span>
            </Link>
          ))}

          <div className="rc-kicker rc-kicker--gap">Fleet</div>
          {filteredFleet.slice(0, 18).map((truck) => (
            <Link key={truck.id} href={`/trucks/${encodeURIComponent(truck.id)}`} className="rc-contact rc-contact--fleet">
              <TruckThumb truck={truck} />
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

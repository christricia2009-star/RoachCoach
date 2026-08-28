export const REGION_ORDER = [
  "Sacramento",
  "Yuba-Sutter",
  "Bay Area",
  "North State",
  "Sierra",
  "Central Valley",
  "Central Coast",
  "Other",
];

export const REGION_AREAS = {
  Sacramento: [
    "Sacramento", "Roseville", "Elk Grove", "Folsom", "Rancho Cordova",
    "Citrus Heights", "Natomas", "Midtown", "West Sacramento", "Davis",
    "Woodland", "Lincoln", "Rocklin", "South Sac", "Arden",
  ],
  "Yuba-Sutter": [
    "Plumas Lake", "Olivehurst", "Marysville", "Yuba City", "Wheatland",
    "Linda", "Live Oak", "Sutter", "Yuba County", "Sutter County",
    "Eufay", "Wheeler Ranch", "Hallwood",
  ],
  "Bay Area": [
    "San Francisco", "Oakland", "San Jose", "Berkeley", "Alameda",
    "Peninsula", "East Bay", "South Bay", "Marin", "Santa Clara",
    "Daly City", "Fremont", "Palo Alto", "Sunnyvale",
  ],
  "North State": [
    "Redding", "Chico", "Red Bluff", "Eureka", "Arcata", "Humboldt",
    "Shasta", "Oroville", "Paradise",
  ],
  Sierra: [
    "Tahoe", "Truckee", "Reno", "Sparks", "South Lake Tahoe",
    "Incline Village", "Kings Beach",
  ],
  "Central Valley": [
    "Fresno", "Stockton", "Modesto", "Bakersfield", "Visalia", "Clovis",
    "Merced", "Turlock", "Madera", "Dinuba", "Hanford",
  ],
  "Central Coast": [
    "Santa Cruz", "Monterey", "Salinas", "Watsonville", "Capitola",
    "Carmel", "Pacific Grove", "Seaside",
  ],
};

export function truckAreas(truck) {
  const region = truckRegion(truck);
  const extra = Array.isArray(truck?.areas) ? truck.areas : [];
  return [...new Set([...extra, ...(REGION_AREAS[region] || []), region].filter(Boolean))];
}

export function truckSearchHaystack(truck) {
  return [
    truck?.name,
    truck?.cuisine_type,
    truckRegion(truck),
    instagramHandle(truck),
    facebookHandle(truck),
    ...truckAreas(truck),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function matchesTruckSearch(truck, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  const hay = truckSearchHaystack(truck);
  return q.split(/\s+/).every((token) => hay.includes(token));
}

export function instagramHandle(truck) {
  const links = Array.isArray(truck?.social_links) ? truck.social_links : [];
  for (const raw of links) {
    const value = String(raw || "").trim();
    const match = value.match(/instagram\.com\/([^/?#]+)/i);
    if (match?.[1]) return match[1].replace(/^@/, "");
    if (value.startsWith("@") && !value.includes(" ")) return value.slice(1);
  }
  return "";
}

export function facebookHandle(truck) {
  const links = Array.isArray(truck?.social_links) ? truck.social_links : [];
  for (const raw of links) {
    const match = String(raw || "").match(/facebook\.com\/([^/?#]+)/i);
    if (match?.[1]) return match[1];
  }
  return "";
}

export function hasSocialPresence(truck) {
  return Boolean(instagramHandle(truck) || facebookHandle(truck));
}

export function avatarCandidates(truck) {
  const out = [];
  const image = String(truck?.image_url || "").trim();
  if (image.startsWith("https://") && image.length < 2000) out.push(image);
  const ig = instagramHandle(truck);
  if (ig) {
    out.push(`https://unavatar.io/instagram/${encodeURIComponent(ig)}`);
  }
  const fb = facebookHandle(truck);
  if (fb) {
    out.push(`https://unavatar.io/facebook/${encodeURIComponent(fb)}`);
  }
  const name = encodeURIComponent(String(truck?.name || "Truck").slice(0, 24));
  out.push(`https://ui-avatars.com/api/?name=${name}&background=ff7a1a&color=fff&size=128&bold=true&format=png`);
  return out;
}

export function avatarUrl(truck) {
  return avatarCandidates(truck)[0] || "";
}

export function truckRegion(truck) {
  const region = String(truck?.region || "").trim();
  return region || "Other";
}

export function relativeTime(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return "";
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function isSightingLive(sighting, now = Date.now()) {
  if (!sighting) return false;
  const expires = sighting.expiresAt ? new Date(sighting.expiresAt).getTime() : null;
  if (expires !== null && expires < now) return false;
  const ts = new Date(sighting.timestamp || 0).getTime();
  return Number.isFinite(ts) && now - ts <= 3 * 60 * 60 * 1000;
}

export function uniqueRecentSightings(sightings, limit = 5, meters = 150) {
  const sorted = [...(sightings || [])].sort(
    (a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)
  );
  const kept = [];
  for (const sighting of sorted) {
    const lat = Number(sighting.latitude);
    const lng = Number(sighting.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    const duplicate = kept.some((existing) => {
      const dLat = ((Number(existing.latitude) - lat) * Math.PI) / 180;
      const dLng = ((Number(existing.longitude) - lng) * Math.PI) / 180;
      const rLat = ((Number(existing.latitude) + lat) * Math.PI) / 360;
      const metersNS = dLat * 6371000;
      const metersEW = dLng * Math.cos(rLat) * 6371000;
      return Math.hypot(metersNS, metersEW) < meters;
    });
    if (!duplicate) {
      kept.push(sighting);
      if (kept.length >= limit) break;
    }
  }
  return kept;
}

export function directionsUrl(lat, lng, name) {
  const dest = `${lat},${lng}`;
  const label = encodeURIComponent(name || dest);
  if (typeof navigator !== "undefined" && /iPhone|iPad|Macintosh/.test(navigator.userAgent)) {
    return `https://maps.apple.com/?daddr=${encodeURIComponent(dest)}&q=${label}`;
  }
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(dest)}`;
}

export function socialLinks(truck) {
  const ig = instagramHandle(truck);
  const fb = facebookHandle(truck);
  const links = [];
  if (ig) links.push({ title: "Instagram", handle: `@${ig}`, href: `https://www.instagram.com/${ig}/` });
  if (fb) links.push({ title: "Facebook", handle: fb, href: `https://www.facebook.com/${fb}` });
  return links;
}

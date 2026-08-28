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

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function pacificYmd(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function addDaysYmd(ymd, days) {
  const [year, month, day] = String(ymd).split("-").map(Number);
  const dt = new Date(Date.UTC(year, month - 1, day + days));
  return dt.toISOString().slice(0, 10);
}

function monthDay(ymd) {
  const [, month, day] = String(ymd).split("-");
  return `${Number(month)}/${Number(day)}`;
}

function mondayOfYmd(ymd) {
  const [year, month, day] = String(ymd).split("-").map(Number);
  const dow = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  const offset = dow === 0 ? 6 : dow - 1;
  return addDaysYmd(ymd, -offset);
}

function parseDayChunk(weekday, date, chunk, sharedPlace = "") {
  const text = String(chunk || "").trim();
  if (!text || /^CLOSED\b/i.test(text) || text === "X") {
    return { weekday, date, closed: true, hours: "", location: "", monthDay: monthDay(date) };
  }
  const at = text.match(/^(.*?)\s+@\s*(.+)$/);
  if (at) {
    return {
      weekday,
      date,
      closed: false,
      hours: at[1].trim(),
      location: at[2].trim(),
      monthDay: monthDay(date),
    };
  }
  const hours = text.replace(/^OPEN\b/i, "").trim();
  return {
    weekday,
    date,
    closed: false,
    hours,
    location: sharedPlace,
    monthDay: monthDay(date),
  };
}

export function parseWeeklySchedule(note) {
  const text = String(note || "").trim();
  if (!text) return null;
  const weekly = text.match(
    /^WEEKLY\s+(\d{4}-\d{2}-\d{2})(?:\s+@\s+([^:]+))?\s*:?\s*(.*)$/is
  );
  if (weekly) {
    const weekStart = mondayOfYmd(weekly[1]);
    const sharedPlace = String(weekly[2] || "").trim();
    const body = weekly[3] || "";
    const chunks = body.split(/\s*;\s*/).map((part) => part.trim()).filter(Boolean);
    const byWeekday = new Map();
    for (const chunk of chunks) {
      const match = chunk.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*(.*)$/i);
      if (!match) continue;
      const wd = match[1].slice(0, 3);
      const titled = wd.charAt(0).toUpperCase() + wd.slice(1).toLowerCase();
      byWeekday.set(titled, match[2].trim());
    }
    const listedClosed = [...byWeekday.values()].some((value) => /^CLOSED\b|^X$/i.test(value));
    const days = WEEKDAYS.map((weekday, index) => {
      const date = addDaysYmd(weekStart, index);
      if (!byWeekday.has(weekday)) {
        if (listedClosed) return parseDayChunk(weekday, date, "CLOSED", sharedPlace);
        return null;
      }
      return parseDayChunk(weekday, date, byWeekday.get(weekday), sharedPlace);
    }).filter(Boolean);
    return { weekStart, days, source: "weekly" };
  }
  const legacy = text.match(
    /^Schedule\s+(\d{4}-\d{2}-\d{2})\s+(\S+)(?:\s+at\s+(.+))?$/i
  );
  if (legacy) {
    const date = legacy[1];
    const [year, month, day] = date.split("-").map(Number);
    const jsDay = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
    const weekday = WEEKDAYS[jsDay === 0 ? 6 : jsDay - 1];
    const hours = String(legacy[2] || "").replace("-", "–");
    const location = String(legacy[3] || "").trim();
    return {
      weekStart: date,
      days: [
        {
          weekday,
          date,
          closed: false,
          hours,
          location,
          monthDay: monthDay(date),
        },
      ],
      source: "legacy",
    };
  }
  return null;
}

export function findWeeklySchedule(sightings) {
  const sorted = [...(sightings || [])].sort(
    (a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)
  );
  let legacySighting = null;
  const legacyDays = [];
  for (const sighting of sorted) {
    const parsed = parseWeeklySchedule(sighting.note);
    if (!parsed) continue;
    if (parsed.source === "weekly") {
      return { ...parsed, sighting };
    }
    legacyDays.push(...parsed.days);
    if (!legacySighting) legacySighting = sighting;
  }
  if (!legacyDays.length) return null;
  const seen = new Set();
  const days = [];
  for (const day of legacyDays) {
    if (seen.has(day.date)) continue;
    seen.add(day.date);
    days.push(day);
  }
  days.sort((a, b) => a.date.localeCompare(b.date));
  return {
    weekStart: days[0].date,
    days,
    sighting: legacySighting,
    source: "legacy",
  };
}

export function scheduleStatus(week, now = new Date()) {
  if (!week?.days?.length) return null;
  const today = pacificYmd(now);
  const todayDay = week.days.find((day) => day.date === today) || null;
  const nextOpen =
    week.days.find((day) => !day.closed && day.location && day.date >= today) || null;
  const lastOpen =
    [...week.days].reverse().find((day) => !day.closed && day.location) || null;
  const isOpenToday = Boolean(todayDay && !todayDay.closed && todayDay.location);
  let headline = "";
  if (isOpenToday) {
    headline = `Today ${todayDay.hours ? `${todayDay.hours} ` : ""}at ${todayDay.location}`;
  } else if (nextOpen) {
    headline = `Next ${nextOpen.weekday} ${nextOpen.hours ? `${nextOpen.hours} ` : ""}at ${nextOpen.location}`;
  } else if (lastOpen) {
    headline = `Closed today · last stop ${lastOpen.weekday} ${lastOpen.hours ? `${lastOpen.hours} ` : ""}at ${lastOpen.location}`;
  } else {
    headline = "Hours on Instagram";
  }
  return {
    today,
    todayDay,
    nextOpen,
    isOpenToday,
    headline: headline.replace(/\s+/g, " ").trim(),
    directionsDay: nextOpen || lastOpen || null,
  };
}

function scheduleDayKey(note) {
  const text = String(note || "");
  const weekly = parseWeeklySchedule(text);
  if (weekly?.source === "legacy" && weekly.days[0]?.date) return weekly.days[0].date;
  const match = text.match(/^Schedule\s+(\d{4}-\d{2}-\d{2})/i);
  return match ? match[1] : "";
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
    const dayKey = scheduleDayKey(sighting.note);
    const duplicate = kept.some((existing) => {
      const existingDay = scheduleDayKey(existing.note);
      if (dayKey && existingDay && dayKey !== existingDay) return false;
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

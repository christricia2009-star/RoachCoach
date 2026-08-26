export const REGION_ORDER = [
  "Sacramento",
  "Bay Area",
  "North State",
  "Sierra",
  "Central Valley",
  "Central Coast",
  "Other",
];

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

export function socialLinks(truck) {
  const ig = instagramHandle(truck);
  const fb = facebookHandle(truck);
  const links = [];
  if (ig) links.push({ title: "Instagram", handle: `@${ig}`, href: `https://www.instagram.com/${ig}/` });
  if (fb) links.push({ title: "Facebook", handle: fb, href: `https://www.facebook.com/${fb}` });
  return links;
}

"""
Uses whichever LLM provider is configured (Anthropic, Grok, or OpenRouter —
see llm_providers.py and .env.example) to extract structured location/time
data from a food truck's casually-written social media caption.

This part is fully functional code — once you have posts (from
social_scraper.py once that's connected to real API/partnership access)
and set the relevant API key(s) in your .env, this will actually parse them.

Example input caption:
    "at the brewery on 5th today from 11-2, see y'all there! 🌮"

Example output:
    {
      "location_text": "the brewery on 5th",
      "start_time": "11:00",
      "end_time": "14:00",
      "confidence": "high"
    }
"""

import base64
import json
import os
import re
from datetime import datetime, timezone

import requests

from llm_providers import complete, complete_with_image

_STREET_RE = re.compile(
    r"\b\d{3,5}\s+[A-Za-z0-9.'\- ]{2,40}?\s"
    r"(?:Blvd|Boulevard|St|Street|Ave|Avenue|Rd|Road|Way|Dr|Drive|"
    r"Ln|Lane|Pkwy|Parkway|Ct|Court|Pl|Place)\b",
    re.IGNORECASE,
)
_AT_RE = re.compile(
    r"\b(?:at|@)\s+([A-Za-z0-9.'&/\- ]{3,50}?)(?:\s+(?:today|tonight|now)|[,.!?\n]|$)",
    re.IGNORECASE,
)


def _llm_extract_enabled() -> bool:
    """OpenRouter (or another LLM key) is used only when regex finds no address."""
    return bool(
        (os.getenv("OPENROUTER_API_KEY") or "").strip()
        or (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        or (os.getenv("XAI_API_KEY") or "").strip()
    )


def _regex_extract(caption: str) -> dict:
    empty = {
        "location_text": None,
        "start_time": None,
        "end_time": None,
        "confidence": "none",
    }
    street = _STREET_RE.search(caption or "")
    if street:
        return {
            "location_text": street.group(0).strip(),
            "start_time": None,
            "end_time": None,
            "confidence": "high",
        }
    at = _AT_RE.search(caption or "")
    if at:
        place = at.group(1).strip(" ,.-")
        if len(place) >= 4:
            return {
                "location_text": place,
                "start_time": None,
                "end_time": None,
                "confidence": "medium",
            }
    return empty

EXTRACTION_PROMPT = """You extract food truck location and time information \
from social media captions. The caption may be casual, use abbreviations, \
or contain no location at all.

Respond ONLY with a JSON object (no other text, no markdown fences) matching \
this shape:
{{
  "location_text": string or null,
  "start_time": string or null (24hr HH:MM format if determinable),
  "end_time": string or null (24hr HH:MM format if determinable),
  "confidence": "high" | "medium" | "low" | "none"
}}

If the caption doesn't mention a location or time at all, set confidence to \
"none" and the other fields to null.

Caption:
\"\"\"{caption}\"\"\"
"""


SCHEDULE_IMAGE_PROMPT = """You read a food-truck Instagram photo. It is often a weekly
schedule graphic (one row/column per weekday, CLOSED vs a park/address), a
flyer, a story screenshot, or a photo with location text overlaid. The caption
may not repeat the address.

Post caption:
\"\"\"{caption}\"\"\"

This post was published (UTC): {posted_at}
Today's date in America/Los_Angeles: {today}

If the image is a WEEKLY hours graphic, extract ALL 7 days (Mon–Sun), including
days marked CLOSED. Do not skip closed days. Do not collapse the week into one
stop. Keep the park/venue name, not just the city.

Respond ONLY with JSON (no markdown):
{{
  "confidence": "high" | "medium" | "low" | "none",
  "kind": "weekly_schedule" | "here_now" | "other",
  "slots": [
    {{
      "date": "YYYY-MM-DD",
      "weekday": "Mon",
      "location_text": "place name, city" or null,
      "start_time": "HH:MM" or null,
      "end_time": "HH:MM" or null,
      "closed": true
    }}
  ]
}}

Resolve weekday + calendar day using the post's week. Example: a graphic
showing "26 WED … Eufay Wood Spray Park, Plumas Lake" near a late-August 2026
post is 2026-08-26, weekday Wed, closed=false.
A row that only says CLOSED has closed=true and location_text=null.
If the image is a single "we're here now" location, kind=here_now and one slot
dated today.
If there is no location, return {{"confidence":"none","kind":"other","slots":[]}}.
"""


def _parse_json_object(raw_text: str) -> dict:
    cleaned = (raw_text or "").replace("```json", "").replace("```", "").strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


def extract_locations_from_image(
    caption: str,
    image_url: str,
    posted_at: datetime | None = None,
) -> dict:
    """Vision pass for schedule graphics and flyers. Empty dict on failure."""
    empty = {"confidence": "none", "slots": [], "location_text": None}
    if not (image_url or "").strip() or not _llm_extract_enabled():
        return empty
    posted = posted_at or datetime.now(timezone.utc)
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        today = datetime.now().date().isoformat()
    prompt = SCHEDULE_IMAGE_PROMPT.format(
        caption=(caption or "")[:500],
        posted_at=posted.isoformat(),
        today=today,
    )
    vision_url = image_url
    try:
        img = requests.get(
            image_url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RoachCoachRadar/1.0)"},
        )
        img.raise_for_status()
        ctype = (img.headers.get("content-type") or "image/jpeg").split(";")[0]
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"
        vision_url = f"data:{ctype};base64,{base64.b64encode(img.content).decode('ascii')}"
    except Exception as exc:
        print(f"[llm_extract] image download failed, trying URL: {exc}")
    try:
        raw = complete_with_image(prompt, vision_url, max_tokens=1200) or ""
    except Exception as exc:
        print(f"[llm_extract] vision failed: {exc}")
        return empty
    parsed = _parse_json_object(raw)
    slots = parsed.get("slots") if isinstance(parsed.get("slots"), list) else []
    usable = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        closed = bool(slot.get("closed"))
        place = (slot.get("location_text") or "").strip() or None
        if place and place.lower() in {"closed", "none", "n/a"}:
            closed = True
            place = None
        if not closed and (not place or len(place) < 4):
            continue
        usable.append(
            {
                "date": slot.get("date"),
                "weekday": slot.get("weekday"),
                "location_text": None if closed else place,
                "start_time": slot.get("start_time"),
                "end_time": slot.get("end_time"),
                "closed": closed,
            }
        )
    open_slots = [slot for slot in usable if not slot["closed"]]
    kind = parsed.get("kind") or (
        "weekly_schedule"
        if len(usable) >= 2 or any(slot["closed"] for slot in usable)
        else ("here_now" if open_slots else "other")
    )
    confidence = parsed.get("confidence") or ("high" if usable else "none")
    location_text = open_slots[0]["location_text"] if open_slots else None
    return {
        "confidence": confidence if usable else "none",
        "kind": kind,
        "slots": usable,
        "location_text": location_text,
        "start_time": open_slots[0].get("start_time") if open_slots else None,
        "end_time": open_slots[0].get("end_time") if open_slots else None,
    }


def extract_location_from_caption(caption: str) -> dict:
    text = (caption or "").strip()
    empty = {
        "location_text": None,
        "start_time": None,
        "end_time": None,
        "confidence": "none",
    }
    # Empty IG/FB posts have no location; skip the LLM call.
    if len(text) < 8:
        return empty

    cheap = _regex_extract(text)
    if cheap.get("confidence") in ("high", "medium") or not _llm_extract_enabled():
        return cheap

    raw_text = complete(EXTRACTION_PROMPT.format(caption=caption), max_tokens=300) or ""

    # Defensive parsing in case the model wraps the JSON in fences anyway
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    if not cleaned:
        return {
            "location_text": None,
            "start_time": None,
            "end_time": None,
            "confidence": "none",
        }

    try:
        parsed = json.loads(cleaned)
        if parsed.get("confidence") in ("high", "medium") and parsed.get("location_text"):
            return parsed
    except json.JSONDecodeError:
        pass
    return cheap


if __name__ == "__main__":
    # Quick manual test — requires the API key for whichever LLM_PROVIDER
    # you've set in your environment (see .env.example).
    sample = "at the brewery on 5th today from 11-2, see y'all there!"
    print(extract_location_from_caption(sample))

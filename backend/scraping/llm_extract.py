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

import json
import os
import re

from llm_providers import complete

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

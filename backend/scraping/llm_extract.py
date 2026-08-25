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
from llm_providers import complete

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
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "location_text": None,
            "start_time": None,
            "end_time": None,
            "confidence": "none",
        }


if __name__ == "__main__":
    # Quick manual test — requires the API key for whichever LLM_PROVIDER
    # you've set in your environment (see .env.example).
    sample = "at the brewery on 5th today from 11-2, see y'all there!"
    print(extract_location_from_caption(sample))

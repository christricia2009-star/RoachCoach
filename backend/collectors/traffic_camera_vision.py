"""
Phase 3 (partial): computer vision on PUBLIC traffic camera feeds.

IMPORTANT SCOPE NOTE: this only works with camera feeds that are genuinely
public and legally accessible without a partnership — many cities publish
these via open-data portals (search "[your city] traffic camera API" or
check the city's open-data portal, e.g. Socrata-based ones often list a
"traffic-cameras" or "cctv" dataset with public image URLs). If your city's
cameras require a login, a private feed, or a data-sharing agreement,
that's back to a partnership requirement — don't try to work around that.

This is genuinely runnable code, not a stub, PROVIDED you supply a real
public camera image URL. Supports vision on Anthropic (Claude), xAI
(Grok), or OpenRouter — pick whichever provider you have a key for. All
three of xAI's grok-4.1-fast and OpenRouter's x-ai/grok-4.1-fast routing
of the same model are genuinely multimodal (confirmed image input
support), not text-only.
"""

import os
import json
import base64
import requests
import anthropic
from openai import OpenAI  # used for xAI + OpenRouter (both OpenAI-compatible)

DETECTION_PROMPT = """You are looking at a single frame from a public \
traffic camera. Respond ONLY with a JSON object (no other text, no \
markdown fences) in this shape:
{
  "likely_food_truck_present": true or false,
  "confidence": "high" | "medium" | "low",
  "reasoning": a short one-sentence explanation,
  "estimated_crowd_size": "none" | "small" | "medium" | "large"
}

A food truck typically appears as a box-shaped vehicle, often with a
serving window, sometimes with a small crowd or line nearby. Do not guess
wildly — if the image is too low-resolution, distant, or ambiguous, set
confidence to "low"."""

# Cheap default models per provider — check current pricing/availability
# before relying on these long-term (mirrors scraping/llm_providers.py's
# DEFAULT_MODELS so the two stay consistent).
VISION_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "grok": "grok-4-1-fast",
    "openrouter": "x-ai/grok-4.1-fast",
}

# Env var each provider falls back to when no per-request key is passed
# (local/CLI testing only — see scheduler.py usage).
_ENV_KEY_NAMES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "grok": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _vision_call(provider: str, api_key: str, model: str, media_type: str, image_b64: str, prompt: str) -> str:
    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return "".join(block.text for block in message.content if hasattr(block, "text")).strip()

    elif provider in ("grok", "openrouter"):
        base_url = "https://api.x.ai/v1" if provider == "grok" else "https://openrouter.ai/api/v1"
        client = OpenAI(api_key=api_key, base_url=base_url)
        data_uri = f"data:{media_type};base64,{image_b64}"
        response = client.chat.completions.create(
            model=model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        )
        return response.choices[0].message.content.strip()

    else:
        raise ValueError(f"Unknown vision provider '{provider}'. Expected anthropic, grok, or openrouter.")


def check_frame_for_truck(image_url: str, provider: str = "anthropic", api_key: str = None, model: str = None, anthropic_api_key: str = None) -> dict:
    """
    Fetches a single frame from a public camera image URL and asks a vision
    model whether a food truck is likely present.

    provider: "anthropic" | "grok" | "openrouter" — which vision-capable
    provider to use. Pass the caller's own key (e.g. from the app's
    per-scan headers) via api_key rather than relying on a server-side env
    var — keeps this consistent with the app's "no server-stored secrets"
    design. Falls back to the matching env var if api_key is omitted.

    anthropic_api_key: deprecated alias for api_key when provider is
    "anthropic" — kept so existing callers (main.py's earlier version)
    don't break; prefer api_key + provider going forward.

    NOTE: many public traffic cameras refresh a static image URL every N
    seconds rather than offering a video stream — that's actually easier to
    work with here, since you just fetch the current frame as an image.
    """
    if anthropic_api_key and not api_key:
        provider = "anthropic"
        api_key = anthropic_api_key

    key = api_key or os.getenv(_ENV_KEY_NAMES.get(provider, ""))
    if not key:
        raise RuntimeError(
            f"No API key available for provider '{provider}' — pass api_key "
            f"or set {_ENV_KEY_NAMES.get(provider, '<unknown env var>')}."
        )
    resolved_model = model or VISION_DEFAULT_MODELS.get(provider)
    if not resolved_model:
        raise ValueError(f"Unknown vision provider '{provider}'.")

    response = requests.get(image_url, timeout=10)
    response.raise_for_status()
    image_b64 = base64.b64encode(response.content).decode("utf-8")
    media_type = response.headers.get("Content-Type", "image/jpeg")

    raw_text = _vision_call(provider, key, resolved_model, media_type, image_b64, DETECTION_PROMPT)
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "likely_food_truck_present": False,
            "confidence": "low",
            "reasoning": "Could not parse model response.",
            "estimated_crowd_size": "none",
        }


def scan_known_cameras(camera_urls: list[str], provider: str = "anthropic", api_key: str = None, model: str = None) -> list[dict]:
    """Runs detection across a curated list of known-public camera image URLs."""
    results = []
    for url in camera_urls:
        try:
            result = check_frame_for_truck(url, provider=provider, api_key=api_key, model=model)
            result["camera_url"] = url
            results.append(result)
        except Exception as e:
            print(f"Failed to check camera {url}: {e}")
    return results


def scan_california_area(
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
    max_cameras: int = None,
    provider: str = "anthropic",
    api_key: str = None,
    model: str = None,
    anthropic_api_key: str = None,
) -> list[dict]:
    """
    Scans real Caltrans CCTV cameras near a given point using the live,
    statewide directory in california_camera_directory.py.

    `max_cameras` defaults to california_camera_directory.MAX_CONCURRENT_CHECKS
    (raised above the standard 9-camera cap if you've set
    HAS_BULK_STREAMING_AGREEMENT = True there, per your written Caltrans
    agreement — keep that flag honest if the agreement's scope changes).
    """
    if anthropic_api_key and not api_key:
        provider = "anthropic"
        api_key = anthropic_api_key

    from california_camera_directory import fetch_all_california_cameras, cameras_near, MAX_CONCURRENT_CHECKS

    if max_cameras is None:
        max_cameras = MAX_CONCURRENT_CHECKS

    all_cameras = fetch_all_california_cameras()
    nearby = cameras_near(all_cameras, latitude, longitude, radius_miles)
    nearby = [cam for cam in nearby if cam.in_service][:max_cameras]

    results = []
    for cam in nearby:
        try:
            result = check_frame_for_truck(cam.current_image_url, provider=provider, api_key=api_key, model=model)
            result["camera_url"] = cam.current_image_url
            result["location_name"] = cam.location_name
            result["latitude"] = cam.latitude
            result["longitude"] = cam.longitude
            result["county"] = cam.county
            results.append(result)
        except Exception as e:
            print(f"Failed to check camera at {cam.location_name}: {e}")
    return results


if __name__ == "__main__":
    # Quick manual test — replace with a real point of interest.
    print("Set ANTHROPIC_API_KEY, XAI_API_KEY, or OPENROUTER_API_KEY and call "
          "scan_california_area(lat, lng, provider=...) to test this module "
          "against live Caltrans cameras.")

"""
Roach Coach Radar
California Traffic Camera Vision

Uses public Caltrans CCTV still images and a multimodal AI provider.

Provider priority:
    1. OpenRouter
    2. xAI / Grok
    3. Anthropic

Environment variables:
    OPENROUTER_API_KEY
    XAI_API_KEY
    ANTHROPIC_API_KEY

Optional:
    VISION_PROVIDER=openrouter
    VISION_MODEL=x-ai/grok-4.1-fast
"""

import os
import json
import base64
from typing import Optional

import requests
from openai import OpenAI


DETECTION_PROMPT = """
You are analyzing a single frame from a public California traffic camera.

Determine whether a FOOD TRUCK is visibly present.

Respond ONLY with valid JSON:

{
  "likely_food_truck_present": true,
  "confidence": "high",
  "reasoning": "short explanation",
  "estimated_crowd_size": "none"
}

Rules:

- A food truck should be a recognizable commercial food-service vehicle.
- Do NOT classify ordinary box trucks, buses, vans, RVs, semis, or passenger vehicles as food trucks.
- If the vehicle is too small, blurry, distant, blocked, or ambiguous, return false with low confidence.
- Do not guess.
- Traffic cameras commonly have poor resolution.
- A truck alone does not prove it is a food truck.
- Only report true when the visual evidence reasonably supports a food truck.

confidence must be:
"high", "medium", or "low"

estimated_crowd_size must be:
"none", "small", "medium", or "large"
"""


VISION_DEFAULT_MODELS = {
    "openrouter": "x-ai/grok-4.1-fast",
    "grok": "grok-4-1-fast",
    "anthropic": "claude-sonnet-4-6",
}


def _get_provider_and_key(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """
    Resolve the vision provider.

    Explicit provider/key wins.

    Otherwise:
        OPENROUTER_API_KEY
        XAI_API_KEY
        ANTHROPIC_API_KEY
    """

    requested_provider = (
        provider or os.getenv("VISION_PROVIDER", "")
    ).strip().lower()

    if api_key:
        if requested_provider:
            return requested_provider, api_key

        # If a key was explicitly supplied but provider wasn't,
        # assume OpenRouter because it is the preferred provider.
        return "openrouter", api_key

    if requested_provider:
        if requested_provider == "openrouter":
            key = os.getenv("OPENROUTER_API_KEY")
            if key:
                return "openrouter", key

        elif requested_provider in ("grok", "xai"):
            key = os.getenv("XAI_API_KEY")
            if key:
                return "grok", key

        elif requested_provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if key:
                return "anthropic", key

        raise RuntimeError(
            f"VISION_PROVIDER='{requested_provider}' was requested "
            "but its API key is not configured."
        )

    # Automatic provider selection.
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        return "openrouter", openrouter_key

    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
        return "grok", xai_key

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        return "anthropic", anthropic_key

    raise RuntimeError(
        "No vision API key configured. Expected one of: "
        "OPENROUTER_API_KEY, XAI_API_KEY, or ANTHROPIC_API_KEY."
    )


def _resolve_model(
    provider: str,
    model: Optional[str] = None,
) -> str:

    if model:
        return model

    configured = os.getenv("VISION_MODEL")

    if configured:
        return configured

    return VISION_DEFAULT_MODELS.get(
        provider,
        "x-ai/grok-4.1-fast",
    )


def _download_image(
    image_url: str,
):
    response = requests.get(
        image_url,
        timeout=20,
        headers={
            "User-Agent": "RoachCoachRadar/1.0",
        },
    )

    response.raise_for_status()

    content_type = (
        response.headers.get("Content-Type", "")
        .split(";")[0]
        .strip()
        .lower()
    )

    if not content_type.startswith("image/"):
        content_type = "image/jpeg"

    return response.content, content_type


def _call_openai_compatible(
    provider: str,
    api_key: str,
    model: str,
    media_type: str,
    image_b64: str,
) -> str:

    if provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    elif provider == "grok":
        base_url = "https://api.x.ai/v1"

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    else:
        raise ValueError(
            f"Unsupported OpenAI-compatible provider: {provider}"
        )

    data_uri = (
        f"data:{media_type};base64,{image_b64}"
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=300,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": DETECTION_PROMPT,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_uri,
                        },
                    },
                ],
            }
        ],
    )

    if not response.choices:
        raise RuntimeError(
            f"{provider} returned no choices."
        )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError(
            f"{provider} returned empty content."
        )

    return content.strip()


def _call_anthropic(
    api_key: str,
    model: str,
    media_type: str,
    image_b64: str,
) -> str:

    import anthropic

    client = anthropic.Anthropic(
        api_key=api_key
    )

    message = client.messages.create(
        model=model,
        max_tokens=300,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": DETECTION_PROMPT,
                    },
                ],
            }
        ],
    )

    parts = []

    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)

    return "".join(parts).strip()


def _parse_detection(
    raw_text: str,
) -> dict:

    cleaned = (
        raw_text
        .replace("```json", "")
        .replace("```JSON", "")
        .replace("```", "")
        .strip()
    )

    # Handle accidental surrounding text.
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        data = json.loads(cleaned)

    except json.JSONDecodeError:
        return {
            "likely_food_truck_present": False,
            "confidence": "low",
            "reasoning": (
                "Vision provider returned an invalid JSON response."
            ),
            "estimated_crowd_size": "none",
        }

    present = bool(
        data.get(
            "likely_food_truck_present",
            False,
        )
    )

    confidence = str(
        data.get(
            "confidence",
            "low",
        )
    ).lower()

    if confidence not in (
        "high",
        "medium",
        "low",
    ):
        confidence = "low"

    crowd = str(
        data.get(
            "estimated_crowd_size",
            "none",
        )
    ).lower()

    if crowd not in (
        "none",
        "small",
        "medium",
        "large",
    ):
        crowd = "none"

    reasoning = str(
        data.get(
            "reasoning",
            "",
        )
    ).strip()

    return {
        "likely_food_truck_present": present,
        "confidence": confidence,
        "reasoning": reasoning,
        "estimated_crowd_size": crowd,
    }


def check_frame_for_truck(
    image_url: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
) -> dict:

    # Backwards compatibility with old callers.
    if anthropic_api_key and not api_key:
        provider = "anthropic"
        api_key = anthropic_api_key

    resolved_provider, resolved_key = (
        _get_provider_and_key(
            provider=provider,
            api_key=api_key,
        )
    )

    resolved_model = _resolve_model(
        resolved_provider,
        model,
    )

    image_bytes, media_type = _download_image(
        image_url
    )

    image_b64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    if resolved_provider == "anthropic":

        raw_text = _call_anthropic(
            api_key=resolved_key,
            model=resolved_model,
            media_type=media_type,
            image_b64=image_b64,
        )

    else:

        raw_text = _call_openai_compatible(
            provider=resolved_provider,
            api_key=resolved_key,
            model=resolved_model,
            media_type=media_type,
            image_b64=image_b64,
        )

    result = _parse_detection(
        raw_text
    )

    # These fields are extremely useful to the radar route.
    result["vision_provider"] = (
        resolved_provider
    )

    result["vision_model"] = (
        resolved_model
    )

    return result


def scan_known_cameras(
    camera_urls: list[str],
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> list[dict]:

    results = []

    for url in camera_urls:

        try:

            result = check_frame_for_truck(
                url,
                provider=provider,
                api_key=api_key,
                model=model,
            )

            result["camera_url"] = url

            results.append(result)

        except Exception as exc:

            print(
                f"[VISION] Camera failed: {url}: {exc}"
            )

    return results


def scan_california_area(
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
    max_cameras: Optional[int] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
) -> list[dict]:

    if anthropic_api_key and not api_key:
        provider = "anthropic"
        api_key = anthropic_api_key

    from california_camera_directory import (
        fetch_all_california_cameras,
        cameras_near,
        MAX_CONCURRENT_CHECKS,
    )

    if max_cameras is None:
        max_cameras = MAX_CONCURRENT_CHECKS

    # Resolve the provider BEFORE scanning so failures are visible.
    resolved_provider, resolved_key = (
        _get_provider_and_key(
            provider=provider,
            api_key=api_key,
        )
    )

    resolved_model = _resolve_model(
        resolved_provider,
        model,
    )

    print(
        f"[VISION] provider={resolved_provider} "
        f"model={resolved_model}"
    )

    all_cameras = (
        fetch_all_california_cameras()
    )

    nearby = cameras_near(
        all_cameras,
        latitude,
        longitude,
        radius_miles,
    )

    nearby = [
        cam
        for cam in nearby
        if cam.in_service
    ][:max_cameras]

    print(
        f"[VISION] cameras={len(nearby)} "
        f"radius={radius_miles}"
    )

    results = []

    for cam in nearby:

        try:

            result = check_frame_for_truck(
                cam.current_image_url,
                provider=resolved_provider,
                api_key=resolved_key,
                model=resolved_model,
            )

            result["camera_url"] = (
                cam.current_image_url
            )

            result["location_name"] = (
                cam.location_name
            )

            result["latitude"] = (
                cam.latitude
            )

            result["longitude"] = (
                cam.longitude
            )

            result["county"] = (
                cam.county
            )

            result["route"] = (
                getattr(cam, "route", None)
            )

            results.append(result)

            print(
                f"[VISION] {cam.location_name}: "
                f"truck={result.get('likely_food_truck_present')} "
                f"confidence={result.get('confidence')}"
            )

        except Exception as exc:

            print(
                f"[VISION] Failed camera "
                f"{cam.location_name}: {exc}"
            )

    return results


if __name__ == "__main__":

    provider, key = _get_provider_and_key()

    print(
        "Vision configuration OK"
    )

    print(
        f"Provider: {provider}"
    )

    print(
        f"Model: {_resolve_model(provider)}"
    )

    print(
        "California camera vision module loaded."
    )

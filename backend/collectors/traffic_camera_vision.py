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
public camera image URL. It uses Claude's vision capability to describe
what's in the frame and flag a likely food truck.
"""

import os
import base64
import requests
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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


def check_frame_for_truck(image_url: str) -> dict:
    """
    Fetches a single frame from a public camera image URL and asks Claude's
    vision capability whether a food truck is likely present.

    NOTE: many public traffic cameras refresh a static image URL every N
    seconds rather than offering a video stream — that's actually easier to
    work with here, since you just fetch the current frame as an image.
    """
    response = requests.get(image_url, timeout=10)
    response.raise_for_status()
    image_b64 = base64.b64encode(response.content).decode("utf-8")

    media_type = response.headers.get("Content-Type", "image/jpeg")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
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
                    {"type": "text", "text": DETECTION_PROMPT},
                ],
            }
        ],
    )

    raw_text = "".join(block.text for block in message.content if hasattr(block, "text")).strip()
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    import json
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "likely_food_truck_present": False,
            "confidence": "low",
            "reasoning": "Could not parse model response.",
            "estimated_crowd_size": "none",
        }


def scan_known_cameras(camera_urls: list[str]) -> list[dict]:
    """Runs detection across a curated list of known-public camera image URLs."""
    results = []
    for url in camera_urls:
        try:
            result = check_frame_for_truck(url)
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
) -> list[dict]:
    """
    Scans real Caltrans CCTV cameras near a given point using the live,
    statewide directory in california_camera_directory.py.

    `max_cameras` defaults to california_camera_directory.MAX_CONCURRENT_CHECKS
    (raised above the standard 9-camera cap if you've set
    HAS_BULK_STREAMING_AGREEMENT = True there, per your written Caltrans
    agreement — keep that flag honest if the agreement's scope changes).
    """
    from california_camera_directory import fetch_all_california_cameras, cameras_near, MAX_CONCURRENT_CHECKS

    if max_cameras is None:
        max_cameras = MAX_CONCURRENT_CHECKS

    all_cameras = fetch_all_california_cameras()
    nearby = cameras_near(all_cameras, latitude, longitude, radius_miles)
    nearby = [cam for cam in nearby if cam.in_service][:max_cameras]

    results = []
    for cam in nearby:
        try:
            result = check_frame_for_truck(cam.current_image_url)
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
    print("Set ANTHROPIC_API_KEY and call scan_california_area(lat, lng) to test this module against live Caltrans cameras.")

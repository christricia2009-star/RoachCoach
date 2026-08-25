"""
Unified LLM provider layer — now supports running MULTIPLE providers at
once, spreading calls across them instead of picking just one.

Two modes, set via LLM_STRATEGY in .env:

  "single"     — uses only LLM_PROVIDER (original behavior)
  "round_robin" — cycles through every provider that has a valid key set,
                  spreading load across them (useful for staying under
                  free-tier rate limits on each individually)
  "fallback"    — tries providers in priority order, only moving to the
                  next one if the current one errors or rate-limits

Model names and pricing shift often — verify current model IDs/pricing on
each provider's site before hardcoding anything long-term. All keys will
be hardcoded later per your note — for now this reads from environment
variables so the code runs as soon as you drop values into .env.
"""

import os
import itertools
from openai import OpenAI  # used for xAI + OpenRouter (both OpenAI-compatible)
import anthropic


def _env(name: str, default: str = "") -> str:
    """GitHub Actions injects missing secrets as empty strings, which
    bypasses os.getenv(..., default). Treat blank as unset."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


# This app is configured for OpenRouter + openai/gpt-5.6-luna. GitHub
# Actions must not pass an empty LLM_PROVIDER secret or complete() used
# to raise ValueError("Unknown provider ''") and kill social scraping.
LLM_STRATEGY = _env("LLM_STRATEGY", "single")  # single | round_robin | fallback
LLM_PROVIDER = _env("LLM_PROVIDER", "openrouter")

# Cheap default models per provider — check current pricing before relying
# on these long-term, since providers change model lineups frequently.
#
# grok-4.1-fast was retired (xAI/OpenRouter now 404 it, pointing at
# grok-4.3 instead) — updated Aug 2026. If you see a
# "<model> is deprecated" 404 in the logs again later, that means these
# need bumping again; check https://openrouter.ai/models?q=grok for
# whatever's current before hardcoding a replacement.
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "grok": "grok-4.3",
    "openrouter": "openai/gpt-5.6-luna",
}

# Separate, cheap default JUST for the web-search step (see
# web_search_complete below) — deliberately NOT the same as
# DEFAULT_MODELS["openrouter"] above.
#
# Grok 4.3 is a REASONING model: it spends output tokens on chain-of-
# thought before ever writing the answer, and that reasoning cost is
# what actually drove the >$1/run bill — reading a handful of search
# results and stating a location doesn't need deep reasoning, so paying
# for it is pure waste here. This default is a fast, non-reasoning model
# instead.
#
# Was google/gemini-3.7-flash — switched to the same openai/gpt-5.6-luna
# model traffic_camera_vision.py already defaults to for its (also
# high-volume, also classification-not-reasoning) calls: Gemini was
# consistently overkill/more expensive than needed for "read a few
# search snippets, state a location," and standardizing on one cheap
# model across both call sites means one thing to watch pricing/
# deprecation on instead of two. Override with LLM_WEB_SEARCH_MODEL if
# you want something else (e.g. google/gemini-3.7-flash or grok-4.3 for
# higher-quality extraction on ambiguous captions, at higher cost).
# Pricing/availability drifts — check
# https://openrouter.ai/models?q=web%20search (filter to plugin-
# compatible, non-reasoning, cheap) before relying on this long-term.
DEFAULT_WEB_SEARCH_MODEL = "openai/gpt-5.6-luna"



def _has_key(name: str) -> bool:
    return bool(_env(name))


def _available_providers() -> list[str]:
    """Returns every provider that has an API key set in the environment,
    in a fixed priority order (used for both round_robin and fallback)."""
    candidates = []
    if _has_key("ANTHROPIC_API_KEY"):
        candidates.append("anthropic")
    if _has_key("XAI_API_KEY"):
        candidates.append("grok")
    if _has_key("OPENROUTER_API_KEY"):
        candidates.append("openrouter")
    return candidates


def _message_text(response) -> str:
    """OpenRouter plugin/search calls sometimes return a choice with
    message.content = None, a list of parts, or text on another field."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""

    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("text"):
                parts.append(str(part["text"]))
            else:
                text = getattr(part, "text", None)
                if text:
                    parts.append(str(text))
        content = "\n".join(parts)
    if content:
        return str(content).strip()

    for attr in ("refusal", "reasoning"):
        extra = getattr(message, attr, None)
        if extra:
            return str(extra).strip()
    return ""


# Round-robin cursor — persists across calls within a process so repeated
# calls actually rotate rather than always starting from the same provider.
_rr_cycle = None


def _next_round_robin_provider() -> str:
    global _rr_cycle
    providers = _available_providers()
    if not providers:
        raise RuntimeError(
            "No LLM provider API keys set. Set at least one of "
            "ANTHROPIC_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY in .env."
        )
    if _rr_cycle is None:
        _rr_cycle = itertools.cycle(providers)
    return next(_rr_cycle)


def _model_for(provider: str) -> str:
    return _env("LLM_MODEL") or DEFAULT_MODELS.get(
        provider, DEFAULT_MODELS["openrouter"]
    )


def _call_provider(provider: str, prompt: str, max_tokens: int) -> str:
    model = _model_for(provider)

    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in message.content if hasattr(block, "text")).strip()

    elif provider == "grok":
        client = OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1")
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return _message_text(response)

    elif provider == "openrouter":
        client = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1")
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return _message_text(response)

    else:
        raise ValueError(f"Unknown provider '{provider}'.")


def complete(prompt: str, max_tokens: int = 300) -> str:
    """
    Sends a single-turn prompt using whichever strategy is configured:

      - "single": always uses LLM_PROVIDER
      - "round_robin": rotates through every provider with a key set
      - "fallback": tries providers in order, moving on if one raises
    """
    strategy = _env("LLM_STRATEGY", "single")

    if strategy == "round_robin":
        provider = _next_round_robin_provider()
        return _call_provider(provider, prompt, max_tokens)

    elif strategy == "fallback":
        providers = _available_providers()
        if not providers:
            raise RuntimeError(
                "No LLM provider API keys set. Set at least one of "
                "ANTHROPIC_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY in .env."
            )
        last_error = None
        for provider in providers:
            try:
                return _call_provider(provider, prompt, max_tokens)
            except Exception as e:
                print(f"[llm_providers] {provider} failed ({e}), trying next provider…")
                last_error = e
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    else:  # "single"
        provider = _env("LLM_PROVIDER", "openrouter")
        if provider not in ("anthropic", "grok", "openrouter"):
            available = _available_providers()
            if "openrouter" in available:
                provider = "openrouter"
            elif available:
                provider = available[0]
            else:
                raise ValueError(
                    f"Unknown provider '{provider}' and no LLM API keys are set."
                )
        return _call_provider(provider, prompt, max_tokens)


def web_search_complete(prompt: str, max_tokens: int = 350, max_results: int = 3) -> str:
    """
    OpenRouter-only. Runs a prompt through OpenRouter's server-side web
    search plugin, so the model's answer is grounded in live search
    results instead of whatever it memorized during training — this is
    what makes "[truck name] location today"-style queries actually work,
    since a plain LLM call has no way to know that.

    This is intentionally separate from complete()/_call_provider() above:
    the round_robin/fallback strategies are about spreading LOAD across
    providers that all do the same thing (plain text completion), but web
    search is a capability only OpenRouter's plugin provides here, so it
    always goes straight to OpenRouter regardless of LLM_STRATEGY/
    LLM_PROVIDER. It also deliberately defaults to a DIFFERENT (cheaper,
    non-reasoning) model than the rest of this file — see
    DEFAULT_WEB_SEARCH_MODEL above — since this step runs once per known
    truck every scan, and reasoning-model costs compound fast at that
    volume. Override with LLM_WEB_SEARCH_MODEL if you want something else
    (e.g. grok-4.3 for higher-quality extraction on ambiguous captions,
    at reasoning-model prices).

    Requires OPENROUTER_API_KEY. Raises RuntimeError if it's not set —
    callers (see scraping/social_scraper.py's search_web_for_truck_location)
    are expected to catch this and treat it the same as "source not
    configured," not as a pipeline-ending failure.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. The web-search step specifically "
            "needs an OpenRouter key — having ANTHROPIC_API_KEY or "
            "XAI_API_KEY set is not enough, since the search plugin is "
            "an OpenRouter-specific feature (it calls Exa.ai under the "
            "hood; see https://openrouter.ai/docs/guides/features/plugins/web-search)."
        )

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    model = _env("LLM_WEB_SEARCH_MODEL") or DEFAULT_WEB_SEARCH_MODEL

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        extra_body={
            "plugins": [
                {"id": "web", "max_results": max_results}
            ]
        },
    )
    return _message_text(response)

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

LLM_STRATEGY = os.getenv("LLM_STRATEGY", "single")  # single | round_robin | fallback
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # used only in "single" mode

# Cheap default models per provider — check current pricing before relying
# on these long-term, since providers change model lineups frequently.
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "grok": "grok-4-1-fast",              # cheapest general xAI tier as of Aug 2026
    "openrouter": "x-ai/grok-4.1-fast",   # same model, routed through OpenRouter
    # OpenRouter also lists free, rate-limited models — check
    # https://openrouter.ai/models filtered by "free" for current options
    # and set LLM_MODEL to one of those IDs if you want zero-cost testing.
}


def _available_providers() -> list[str]:
    """Returns every provider that has an API key set in the environment,
    in a fixed priority order (used for both round_robin and fallback)."""
    candidates = []
    if os.getenv("ANTHROPIC_API_KEY"):
        candidates.append("anthropic")
    if os.getenv("XAI_API_KEY"):
        candidates.append("grok")
    if os.getenv("OPENROUTER_API_KEY"):
        candidates.append("openrouter")
    return candidates


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
    return os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["anthropic"])


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
        return response.choices[0].message.content.strip()

    elif provider == "openrouter":
        client = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1")
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()

    else:
        raise ValueError(f"Unknown provider '{provider}'.")


def complete(prompt: str, max_tokens: int = 300) -> str:
    """
    Sends a single-turn prompt using whichever strategy is configured:

      - "single": always uses LLM_PROVIDER
      - "round_robin": rotates through every provider with a key set
      - "fallback": tries providers in order, moving on if one raises
    """
    if LLM_STRATEGY == "round_robin":
        provider = _next_round_robin_provider()
        return _call_provider(provider, prompt, max_tokens)

    elif LLM_STRATEGY == "fallback":
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
        return _call_provider(LLM_PROVIDER, prompt, max_tokens)


def web_search_complete(prompt: str, max_tokens: int = 500, max_results: int = 4) -> str:
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
    LLM_PROVIDER.

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
    model = os.getenv("LLM_WEB_SEARCH_MODEL") or _model_for("openrouter")

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        # OpenRouter-specific field — the OpenAI client passes unknown
        # kwargs straight through in the request body via extra_body.
        extra_body={
            "plugins": [
                {"id": "web", "max_results": max_results}
            ]
        },
    )
    return response.choices[0].message.content.strip()

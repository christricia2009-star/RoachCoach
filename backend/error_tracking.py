"""
Error tracking — replaces the "except Exception: print(...)" pattern
that was previously the ONLY trace of a failure anywhere in this app
(and specifically how save_unmatched_detection() calling a function
that didn't exist ran in production, undetected, for however long: the
only evidence was a print() line in a Vercel log nobody was watching).

Usage:

    from backend import error_tracking
    error_tracking.init()   # call once, at process startup

    try:
        risky_thing()
    except Exception:
        error_tracking.report("risky_thing failed", extra={"foo": bar})

If SENTRY_DSN is set, exceptions go to Sentry (free tier is enough for
this app's volume) with the message/extra context attached, so a
failure shows up somewhere a human will actually see it. If SENTRY_DSN
is NOT set, report() still prints the full traceback (so behavior
without any setup is exactly as good as before, never worse) and does
not raise — configuring Sentry is opt-in, but every call site using
this helper instead of a bare print() is not.
"""

import os
import traceback
from typing import Any, Optional

_sentry_enabled = False


def init() -> bool:
    """
    Call once at process startup (main.py module load, scheduler.py
    main()). Returns True if Sentry is actually active.
    """

    global _sentry_enabled

    dsn = os.getenv("SENTRY_DSN")

    if not dsn:
        print(
            "error_tracking: SENTRY_DSN not set — exceptions will "
            "still be printed locally, but nothing is being sent to "
            "Sentry. Set SENTRY_DSN to get real alerting."
        )
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv(
                "CLOUDKIT_ENVIRONMENT", "production"
            ),
            traces_sample_rate=0.0,
        )
        _sentry_enabled = True
        return True

    except Exception:
        print(
            "error_tracking: sentry_sdk.init() failed — falling back "
            "to local-only error printing:\n" + traceback.format_exc()
        )
        return False


def report(
    message: str,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    Call from inside an `except Exception:` block. Always prints the
    full traceback locally (so log-tailing still works exactly like
    before). Additionally sends to Sentry if init() was called and a
    DSN was configured.
    """

    print(f"{message}:\n" + traceback.format_exc())

    if not _sentry_enabled:
        return

    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            if extra:
                for key, value in extra.items():
                    scope.set_extra(key, value)
            scope.set_extra("message", message)
            sentry_sdk.capture_exception()

    except Exception:
        # Never let error reporting itself take down the request path.
        print(
            "error_tracking: failed to report to Sentry:\n"
            + traceback.format_exc()
        )

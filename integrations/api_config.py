"""Central API endpoint configuration and transport safety checks.

The internal HTADC proxy used by this project is currently HTTP-only.  Sending
an API key over plaintext HTTP is dangerous, so plaintext non-loopback
endpoints require an explicit opt-in via ``MOTRACK_ALLOW_INSECURE_HTTP=1``.
"""
from __future__ import annotations

import os
import warnings
from urllib.parse import urlparse

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_loopback(host: str | None) -> bool:
    return (host or "").lower() in LOOPBACK_HOSTS


def resolve_base_url(default: str | None = None) -> str:
    """Return a validated OpenAI-compatible base URL.

    ``MOTRACK_API_BASE_URL`` always wins.  ``default`` is only used when the
    environment variable is absent, which lets callers keep a documented
    project default while still allowing a portable override.
    """
    raw = (os.getenv("MOTRACK_API_BASE_URL") or default or "").strip().rstrip("/")
    if not raw:
        raise RuntimeError(
            "MOTRACK_API_BASE_URL is not set; configure a secure https:// endpoint "
            "or explicitly opt in to the trusted internal HTTP proxy."
        )
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"invalid MOTRACK_API_BASE_URL: {raw!r}")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        if os.getenv("MOTRACK_ALLOW_INSECURE_HTTP") != "1":
            raise RuntimeError(
                "Refusing to send API credentials over plaintext HTTP. "
                "Set MOTRACK_API_BASE_URL to an https:// endpoint, or set "
                "MOTRACK_ALLOW_INSECURE_HTTP=1 only for a trusted internal proxy."
            )
        warnings.warn(
            "Using a plaintext HTTP API endpoint because "
            "MOTRACK_ALLOW_INSECURE_HTTP=1. API keys are visible to the network path.",
            RuntimeWarning,
            stacklevel=2,
        )
    return raw

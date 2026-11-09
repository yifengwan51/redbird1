"""Local VIP membership: redemption codes unlock the AI editor for a browser.

There is no payment integration.  An operator hands out codes; a code turns
into a random bearer token kept by the browser.  Only SHA-256 hashes of
tokens are stored.  Codes come from ``MOTRACK_VIP_CODES`` (comma separated) or
``.secrets/vip_codes`` (one per line, created with one fresh code if absent).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"
CODES_FILE = SECRETS / "vip_codes"
TOKENS_FILE = SECRETS / "vip_tokens.json"
MAX_ATTEMPTS_PER_MINUTE = 8

_lock = threading.Lock()
_attempts: list[float] = []


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_codes() -> Path:
    """Create the codes file with one code on first run; return its path."""
    if not CODES_FILE.exists() and not os.getenv("MOTRACK_VIP_CODES"):
        SECRETS.mkdir(mode=0o700, exist_ok=True)
        code = "MOTRACK-" + secrets.token_hex(4).upper()
        CODES_FILE.write_text(code + "\n", encoding="utf-8")
        os.chmod(CODES_FILE, 0o600)
    return CODES_FILE


def _codes() -> list[str]:
    raw = os.getenv("MOTRACK_VIP_CODES")
    if raw is None and CODES_FILE.is_file():
        raw = CODES_FILE.read_text(encoding="utf-8")
    return [c.strip().upper() for c in (raw or "").replace(",", "\n").splitlines() if c.strip()]


def _tokens() -> dict[str, dict]:
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def activate(code: str) -> str:
    """Return a new bearer token for a valid code; raise ValueError otherwise."""
    with _lock:
        now = time.monotonic()
        _attempts[:] = [t for t in _attempts if now - t < 60]
        if len(_attempts) >= MAX_ATTEMPTS_PER_MINUTE:
            raise PermissionError("too many attempts")
        _attempts.append(now)
        given = (code or "").strip().upper()
        if not given or not any(hmac.compare_digest(given, c) for c in _codes()):
            raise ValueError("invalid code")
        token = secrets.token_urlsafe(24)
        tokens = _tokens()
        tokens[_hash(token)] = {"activated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "code": _hash(given)[:12]}
        SECRETS.mkdir(mode=0o700, exist_ok=True)
        partial = TOKENS_FILE.with_suffix(".part")
        partial.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        os.chmod(partial, 0o600)
        os.replace(partial, TOKENS_FILE)
        return token


def dev_mode() -> bool:
    """During development everyone is VIP; set MOTRACK_VIP_MODE=prod to enforce codes."""
    return os.getenv("MOTRACK_VIP_MODE", "dev").strip().lower() != "prod"


def is_vip(token: str | None) -> bool:
    if dev_mode():
        return True
    if not token or len(token) > 128:
        return False
    return _hash(token) in _tokens()

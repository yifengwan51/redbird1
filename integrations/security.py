"""Shared validation helpers for untrusted web/API input.

The web layer must never turn a client-supplied identifier into a filesystem
path without validation.  These helpers are deliberately dependency-free so
they can be unit-tested without importing torch, OpenCV, or FastAPI.
"""
from __future__ import annotations

import re
from pathlib import Path

# UUID-derived IDs, ``validation-doug`` style smoke-test IDs and the web's
# ``lw-<hex>`` job IDs are all accepted.  Path separators, dots and spaces are
# intentionally rejected because this value is also used as a directory name.
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_session_id(value: object) -> str:
    """Return a safe session ID or raise ``ValueError``.

    A session ID is used as a single path component under ``outputs/``.  It
    must therefore never contain ``/``, ``\\``, ``..``, whitespace, or a
    leading separator.
    """
    session_id = str(value or "").strip()
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("invalid session_id: expected 1-64 letters, digits, '-' or '_'")
    return session_id


def ensure_inside(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and require it to live under ``root``.

    Symlinks are resolved before the check, so a link inside the project that
    points outside is rejected as well.
    """
    root = root.resolve()
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path must stay under {root}")
    return candidate


def session_directory(root: Path, base: Path, session_id: object) -> Path:
    """Build and validate ``<base>/<session_id>`` below ``root``."""
    session_id = validate_session_id(session_id)
    directory = ensure_inside(root, base / session_id)
    if root not in directory.parents:
        raise ValueError("session directory must not be the project root")
    return directory

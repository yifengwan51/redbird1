"""Open site, gated AI: free AI uses, then a name and the owner's approval.

Everyone can open the site.  Each browser gets an anonymous visitor cookie;
the AI features (AI 剪辑师 edits and chat, AI 复盘) are free FREE_AI_USES times,
after which the visitor enters a name and waits until the owner approves it on
the admin page (/app/admin.html).  The owner's own devices (this computer,
or a phone signed in with the access code / QR link) are never limited.

Only SHA-256 hashes of visitor tokens are stored; the visible visitor id is a
short prefix of that hash.  State lives in .secrets/ (mode 600).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"
VISITORS = SECRETS / "visitors.json"
SETTINGS = SECRETS / "access_settings.json"
COOKIE = "motrack_visitor"
COOKIE_DAYS = 365
DEFAULTS = {"public": True, "free_ai_uses": 6, "ip_daily_free": 30, "visitor_uploads": 3}
STATUSES = ("free", "pending", "approved", "rejected")

_lock = threading.Lock()
_ip_uses: dict[str, list[float]] = {}
_ip_applies: dict[str, list[float]] = {}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def visitor_id(token: str | None) -> str | None:
    """Short public id for a cookie token, or None for a missing or malformed one."""
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        return None
    return _hash(token)[:16]


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, data: Any) -> None:
    SECRETS.mkdir(mode=0o700, exist_ok=True)
    part = path.with_name(f".{path.name}.part")
    part.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(part, 0o600)
    os.replace(part, path)


def settings() -> dict[str, Any]:
    return {**DEFAULTS, **{k: v for k, v in _load(SETTINGS, {}).items() if k in DEFAULTS}}


def update_settings(changes: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = settings()
        if "public" in changes:
            current["public"] = bool(changes["public"])
        for key, low, high in (("free_ai_uses", 0, 100), ("ip_daily_free", 1, 1000), ("visitor_uploads", 0, 30)):
            if key in changes:
                try:
                    current[key] = max(low, min(high, int(changes[key])))
                except (TypeError, ValueError):
                    raise ValueError(f"{key} 需要是整数")
        _save(SETTINGS, current)
        return current


def _visitors() -> dict[str, dict[str, Any]]:
    return _load(VISITORS, {})


def _record(vid: str) -> dict[str, Any]:
    return _visitors().get(vid) or {"status": "free", "uses": 0, "first_seen": time.time()}


def status(vid: str | None) -> dict[str, Any]:
    """What the page needs to show: status, uses left, the submitted name."""
    if vid is None:
        return {"status": "free", "uses": 0, "left": settings()["free_ai_uses"], "name": None}
    rec = _record(vid)
    free = settings()["free_ai_uses"]
    left = None if rec["status"] == "approved" else max(0, free - rec.get("uses", 0))
    return {"status": rec["status"], "uses": rec.get("uses", 0), "left": left, "name": rec.get("name")}


class Denied(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _recent(store: dict[str, list[float]], key: str, window: float) -> list[float]:
    now = time.time()
    store[key] = [t for t in store.get(key, []) if now - t < window]
    return store[key]


def use_ai(vid: str | None, ip: str) -> dict[str, Any]:
    """Count one AI use, or raise Denied with what the visitor must do next."""
    with _lock:
        if vid is None:
            raise Denied("AI_LOGIN_REQUIRED", "请刷新页面后再试")
        data = _visitors()
        rec = data.get(vid) or {"status": "free", "uses": 0, "first_seen": time.time()}
        cfg = settings()
        if rec["status"] == "pending":
            raise Denied("AI_PENDING", "你的申请正在审核，通过后就能继续使用 AI 功能")
        if rec["status"] == "rejected":
            raise Denied("AI_REJECTED", "你的申请没有通过，如有疑问请联系管理员")
        if rec["status"] != "approved":
            if rec.get("uses", 0) >= cfg["free_ai_uses"]:
                raise Denied("AI_LOGIN_REQUIRED", f"免费的 {cfg['free_ai_uses']} 次 AI 体验用完了，留下姓名，审核通过后就能继续使用")
            # one network cannot farm free uses by clearing cookies
            if len(_recent(_ip_uses, ip or "?", 86400)) >= cfg["ip_daily_free"]:
                raise Denied("AI_LOGIN_REQUIRED", "这个网络今天的免费次数用完了，留下姓名，审核通过后就能继续使用")
            _ip_uses[ip or "?"].append(time.time())
        rec["uses"] = rec.get("uses", 0) + 1
        rec["last_used"] = time.time()
        data[vid] = rec
        _save(VISITORS, data)
        return status_from(rec, cfg)


def status_from(rec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    left = None if rec["status"] == "approved" else max(0, cfg["free_ai_uses"] - rec.get("uses", 0))
    return {"status": rec["status"], "uses": rec.get("uses", 0), "left": left, "name": rec.get("name")}


def clean_name(value: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f<>]", "", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)[:limit]


def apply(vid: str | None, name: Any, note: Any, ip: str) -> dict[str, Any]:
    with _lock:
        if vid is None:
            raise ValueError("请刷新页面后再试")
        if len(_recent(_ip_applies, ip or "?", 3600)) >= 5:
            raise PermissionError("提交太频繁，请一小时后再试")
        name, note = clean_name(name, 20), clean_name(note, 60)
        if len(name) < 2:
            raise ValueError("请填写姓名（至少 2 个字）")
        data = _visitors()
        rec = data.get(vid) or {"status": "free", "uses": 0, "first_seen": time.time()}
        if rec["status"] == "approved":
            return status_from(rec, settings())
        if rec["status"] == "rejected":
            raise ValueError("你的申请没有通过，如有疑问请联系管理员")
        _ip_applies.setdefault(ip or "?", []).append(time.time())
        rec.update(status="pending", name=name, note=note, applied=time.time(), ip=(ip or "")[:45])
        data[vid] = rec
        _save(VISITORS, data)
        return status_from(rec, settings())


def decide(vid: str, action: str) -> dict[str, Any]:
    """Admin: approve / reject / revoke (back to free with no uses left) / reset (fresh free uses)."""
    if action not in ("approve", "reject", "revoke", "reset"):
        raise ValueError("未知操作")
    with _lock:
        data = _visitors()
        if vid not in data:
            raise KeyError(vid)
        rec = data[vid]
        if action == "approve":
            rec.update(status="approved", decided=time.time())
        elif action == "reject":
            rec.update(status="rejected", decided=time.time())
        elif action == "revoke":
            rec.update(status="free", uses=settings()["free_ai_uses"], decided=time.time())
        else:
            rec.update(status="free", uses=0, decided=time.time())
        _save(VISITORS, data)
        return {"id": vid, **rec}


def listing() -> dict[str, Any]:
    data = _visitors()
    rows = [{"id": k, "status": v.get("status", "free"), "name": v.get("name"), "note": v.get("note"),
             "uses": v.get("uses", 0), "applied": v.get("applied"), "decided": v.get("decided"),
             "first_seen": v.get("first_seen"), "last_used": v.get("last_used"), "ip": v.get("ip")}
            for k, v in data.items()]
    rows.sort(key=lambda r: -(r.get("applied") or r.get("last_used") or r.get("first_seen") or 0))
    counts = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    return {"visitors": rows, "counts": counts, "settings": settings()}

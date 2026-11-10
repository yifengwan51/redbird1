"""Use MoTrack from a phone, anywhere: access code + public HTTPS tunnel.

The server still binds to 127.0.0.1.  ``cloudflared`` opens an outbound
quick tunnel and forwards public HTTPS traffic to it, so no firewall port is
opened.  Requests that arrive through the tunnel (or with any forwarding
header, or a Host that is not loopback) are "remote" and must log in with
the access code; the QR code on the desktop page carries a permanent login
link (valid until reset) that logs a phone in directly.  Only SHA-256 hashes
of session tokens are stored.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"
CODE_FILE = SECRETS / "remote_code"
SESSIONS_FILE = SECRETS / "remote_sessions.json"
LINK_FILE = SECRETS / "remote_link"
STATE_FILE = ROOT / "outputs" / "cloudflared.json"
CLOUDFLARED = ROOT / "tools" / "cloudflared" / "cloudflared"
COOKIE = "motrack_session"
SESSION_DAYS = 30
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
FORWARD_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "x-forwarded-host", "forwarded", "cf-ray")

_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------- who is asking ----------
def is_remote(headers: dict[str, str]) -> bool:
    """True unless the request plainly came from this machine's browser."""
    if any(headers.get(h) for h in FORWARD_HEADERS):
        return True
    host = (headers.get("host") or "").lower()
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    return name not in LOOPBACK


def client_ip(headers: dict[str, str], fallback: str = "") -> str:
    return headers.get("cf-connecting-ip") or (headers.get("x-forwarded-for") or "").split(",")[0].strip() or fallback


# ---------- access code ----------
def access_code() -> str:
    """The 8-character code, created on first use (shown as ABCD-EFGH)."""
    if not CODE_FILE.is_file():
        SECRETS.mkdir(mode=0o700, exist_ok=True)
        CODE_FILE.write_text("".join(secrets.choice(ALPHABET) for _ in range(8)) + "\n", encoding="utf-8")
        os.chmod(CODE_FILE, 0o600)
    return CODE_FILE.read_text(encoding="utf-8").strip()


def pretty_code() -> str:
    code = access_code()
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


def _rate_ok(ip: str) -> bool:
    """8 tries a minute and 30 an hour per address, 30 a minute overall."""
    now = time.monotonic()
    hour = ip + ":h"
    with _lock:
        for key, window in ((ip, 60), ("*", 60), (hour, 3600)):
            _attempts[key] = [t for t in _attempts.get(key, []) if now - t < window]
        if len(_attempts[ip]) >= 8 or len(_attempts["*"]) >= 30 or len(_attempts[hour]) >= 30:
            return False
        for key in (ip, "*", hour):
            _attempts[key].append(now)
        return True


def check_code(code: str, ip: str) -> bool:
    if not _rate_ok(ip or "?"):
        raise PermissionError("too many attempts")
    given = re.sub(r"[^A-Za-z0-9]", "", code or "").upper()
    return bool(given) and hmac.compare_digest(given, access_code())


# ---------- sessions ----------
def _sessions() -> dict[str, float]:
    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in data.items() if v > now}


def new_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        sessions = _sessions()
        sessions[_hash(token)] = time.time() + SESSION_DAYS * 86400
        SECRETS.mkdir(mode=0o700, exist_ok=True)
        part = SESSIONS_FILE.with_suffix(".part")
        part.write_text(json.dumps(sessions), encoding="utf-8")
        os.chmod(part, 0o600)
        os.replace(part, SESSIONS_FILE)
    return token


def valid_session(token: str | None) -> bool:
    return bool(token) and len(token) <= 128 and _hash(token) in _sessions()


def login_link_token() -> str:
    """The token in the QR code.  Permanent and reusable until reset_link()."""
    with _lock:
        if not LINK_FILE.is_file():
            SECRETS.mkdir(mode=0o700, exist_ok=True)
            LINK_FILE.write_text(secrets.token_urlsafe(24) + "\n", encoding="utf-8")
            os.chmod(LINK_FILE, 0o600)
        return LINK_FILE.read_text(encoding="utf-8").strip()


def use_link(token: str) -> bool:
    return bool(token) and len(token) <= 128 and hmac.compare_digest(token.encode(), login_link_token().encode())


def reset_link() -> str:
    """New QR code; the old one and every phone signed in so far stop working."""
    with _lock:
        LINK_FILE.unlink(missing_ok=True)
        SESSIONS_FILE.unlink(missing_ok=True)
    return login_link_token()


# ---------- public tunnel ----------
class Tunnel:
    """A cloudflared quick tunnel (https://*.trycloudflare.com).

    cloudflared runs detached from the web server and is found again through
    its state file, so restarting MoTrack keeps the same public URL; the QR
    code on a phone keeps working.  The URL only changes when cloudflared
    itself stops (reboot, "关闭手机访问", network loss).
    """

    def __init__(self) -> None:
        self.error: str | None = None
        self.port = int(os.getenv("MOTRACK_PORT", "8765"))
        self.metrics = f"127.0.0.1:{self.port + 20000}"
        self._proc: subprocess.Popen | None = None
        self._guard = threading.Lock()

    def _state(self) -> dict | None:
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            cmd = Path(f"/proc/{int(state['pid'])}/cmdline").read_bytes().split(b"\0")
        except (OSError, ValueError, KeyError, TypeError):
            return None
        # A live cloudflared tunnelling to *this* server, not a zombie or a reused PID.
        if cmd and cmd[0].endswith(b"cloudflared") and f"http://127.0.0.1:{self.port}".encode() in cmd:
            return state
        return None

    @property
    def running(self) -> bool:
        return self._state() is not None

    @property
    def url(self) -> str | None:
        state = self._state()
        if not state:
            return None
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
            with opener.open(f"http://{state['metrics']}/quicktunnel", timeout=1.5) as res:
                host = json.load(res).get("hostname")
        except (OSError, ValueError):
            return None
        return f"https://{host}" if host else None

    def start(self) -> None:
        with self._guard:
            if self.running:
                return  # keep the existing tunnel and its URL
            if not CLOUDFLARED.is_file():
                self.error = "缺少 tools/cloudflared/cloudflared"
                return
            self.error = None
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            log = (STATE_FILE.parent / "cloudflared.log").open("ab")
            try:
                self._proc = subprocess.Popen(
                    [str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--grace-period", "2s",
                     "--metrics", self.metrics, "--url", f"http://127.0.0.1:{self.port}"],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            except OSError as exc:
                self.error = f"无法启动手机访问（{type(exc).__name__}）"
                return
            finally:
                log.close()
            STATE_FILE.write_text(json.dumps({"pid": self._proc.pid, "metrics": self.metrics}), encoding="utf-8")

    def stop(self) -> None:
        with self._guard:
            state = self._state()
            if state:
                pid = int(state["pid"])
                try:
                    os.kill(pid, signal.SIGTERM)
                    for _ in range(40):
                        time.sleep(0.1)
                        if not Path(f"/proc/{pid}/cmdline").exists() or not Path(f"/proc/{pid}/cmdline").read_bytes():
                            break
                    else:
                        os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            if self._proc is not None:
                try:
                    self._proc.wait(1)
                except subprocess.TimeoutExpired:
                    pass
                self._proc = None
            STATE_FILE.unlink(missing_ok=True)

    def status(self) -> dict:
        running = self.running
        error = self.error
        if not running and not error and STATE_FILE.exists():
            error = "手机访问已断开，点「开启手机访问」重新连接"
        return {"running": running, "url": self.url if running else None, "error": None if running else error}


tunnel = Tunnel()


def qr_svg(text: str) -> str:
    import segno
    return segno.make(text, error="m").svg_data_uri(scale=6, border=2, dark="#0b1220", light="#ffffff")

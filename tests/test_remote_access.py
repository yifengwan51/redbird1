"""Phone access gate and chunked uploads, through the real FastAPI app."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from integrations import remote

try:
    from fastapi.testclient import TestClient
    import web.backend.app as web
    HAVE_APP = True
except Exception:  # pragma: no cover - optional deps
    HAVE_APP = False

LOCAL = {"host": "127.0.0.1:8765"}
PHONE = {"host": "abc.trycloudflare.com", "cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "203.0.113.9"}


class RemoteDetectionTests(unittest.TestCase):
    def test_local_vs_remote(self):
        self.assertFalse(remote.is_remote({"host": "127.0.0.1:8765"}))
        self.assertFalse(remote.is_remote({"host": "localhost:8765"}))
        self.assertTrue(remote.is_remote({"host": "127.0.0.1:8765", "cf-connecting-ip": "1.2.3.4"}))
        self.assertTrue(remote.is_remote({"host": "evil.example:8765"}))  # DNS rebinding


@unittest.skipUnless(HAVE_APP, "web app dependencies are unavailable")
class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patch = mock.patch.multiple(remote, SECRETS=self.tmp, CODE_FILE=self.tmp / "code", SESSIONS_FILE=self.tmp / "s.json",
                                         LINK_FILE=self.tmp / "link", STATE_FILE=self.tmp / "cloudflared.json")
        self.patch.start()
        remote._attempts.clear()
        self.client = TestClient(web.app, base_url="http://127.0.0.1:8765")

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_local_browser_needs_no_login(self):
        self.assertEqual(self.client.get("/api/v1/health", headers=LOCAL).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/videos", headers=LOCAL).status_code, 200)

    def test_phone_must_log_in(self):
        r = self.client.get("/api/v1/videos", headers=PHONE)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["code"], "LOGIN_REQUIRED")
        r = self.client.get("/app/index.html", headers=PHONE, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/app/login.html"))
        self.assertEqual(self.client.get("/app/login.html", headers=PHONE).status_code, 200)
        self.assertEqual(self.client.get("/app/manifest.json", headers=PHONE).status_code, 200)

    def test_code_login_sets_session(self):
        self.assertEqual(self.client.post("/api/v1/login", json={"code": "WRONG"}, headers=PHONE).status_code, 400)
        code = remote.pretty_code().lower()  # case and dash don't matter
        r = self.client.post("/api/v1/login", json={"code": code}, headers=PHONE)
        self.assertEqual(r.status_code, 200)
        cookie = r.cookies.get(remote.COOKIE)
        self.assertTrue(cookie)
        self.assertIn("httponly", r.headers["set-cookie"].lower())
        self.assertEqual(self.client.get("/api/v1/videos", headers=PHONE, cookies={remote.COOKIE: cookie}).status_code, 200)

    def test_qr_link_is_permanent_until_reset(self):
        token = remote.login_link_token()
        self.assertEqual(token, remote.login_link_token())  # stable across calls and restarts
        for _ in range(3):  # scan as often as you like
            r = self.client.get(f"/go/{token}", headers=PHONE, follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (302, "/app/index.html"))
            self.assertTrue(r.cookies.get(remote.COOKIE))
        session = r.cookies.get(remote.COOKIE)
        new = remote.reset_link()
        self.assertNotEqual(new, token)
        old = self.client.get(f"/go/{token}", headers=PHONE, follow_redirects=False)
        self.assertIn("reset", old.headers["location"])
        self.assertFalse(remote.valid_session(session))  # reset also signs out every phone
        self.assertEqual(self.client.get(f"/go/{new}", headers=PHONE, follow_redirects=False).headers["location"], "/app/index.html")

    def test_tunnel_state_ignores_dead_or_foreign_pid(self):
        remote.STATE_FILE.write_text('{"pid": 1, "metrics": "127.0.0.1:1"}', encoding="utf-8")  # pid 1 is init, not cloudflared
        self.assertFalse(remote.Tunnel().running)
        self.assertEqual(remote.Tunnel().status()["error"], "手机访问已断开，点「开启手机访问」重新连接")

    def test_rate_limit_and_desktop_only_panel(self):
        for _ in range(8):
            self.client.post("/api/v1/login", json={"code": "NOPE"}, headers=PHONE)
        self.assertEqual(self.client.post("/api/v1/login", json={"code": remote.access_code()}, headers=PHONE).status_code, 429)
        token = remote.new_session()
        self.assertEqual(self.client.get("/api/v1/remote", headers=PHONE, cookies={remote.COOKIE: token}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/remote", headers=LOCAL).status_code, 200)

    def test_cross_site_write_rejected(self):
        r = self.client.post("/api/v1/chat", json={"message": "hi"}, headers=LOCAL | {"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)


FFMPEG = Path(__file__).parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg"


@unittest.skipUnless(HAVE_APP and FFMPEG.is_file(), "needs the web app and project FFmpeg")
class UploadTests(unittest.TestCase):
    """A vertical HEVC .mov, like an iPhone clip, uploaded in chunks."""

    def setUp(self):
        self.client = TestClient(web.app, base_url="http://127.0.0.1:8765")
        self.tmp = Path(tempfile.mkdtemp())
        self.clip = self.tmp / "IMG_0001.MOV"
        landscape = self.tmp / "landscape.mov"
        subprocess.run([str(FFMPEG), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60:duration=6",
                        "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1",
                        "-c:a", "aac", "-shortest", str(landscape)], check=True, timeout=120)
        # Phones store "held upright" as a display-matrix rotation, not as pixels.
        subprocess.run([str(FFMPEG), "-y", "-v", "error", "-display_rotation:v:0", "90", "-i", str(landscape),
                        "-c", "copy", str(self.clip)], check=True, timeout=60)
        self.uid = None

    def tearDown(self):
        if self.uid:
            for _ in range(60):
                if (web.uploads.get(self.uid) or {}).get("status") not in ("processing", "analyzing"):
                    break
                time.sleep(1)
            self.client.delete(f"/api/v1/videos/{self.uid}", headers=LOCAL)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chunked_upload_resume_and_normalise(self):
        data = self.clip.read_bytes()
        started = self.client.post("/api/v1/uploads", json={"name": self.clip.name, "size": len(data)}, headers=LOCAL).json()
        self.uid = started["id"]
        half = len(data) // 2
        self.assertEqual(self.client.put(f"/api/v1/uploads/{self.uid}?offset=0", content=data[:half], headers=LOCAL).json()["received"], half)
        stale = self.client.put(f"/api/v1/uploads/{self.uid}?offset=0", content=data[:half], headers=LOCAL)  # a retried chunk
        self.assertEqual((stale.status_code, stale.json()["expected"]), (409, half))
        self.client.put(f"/api/v1/uploads/{self.uid}?offset={half}", content=data[half:], headers=LOCAL)
        self.assertEqual(self.client.post(f"/api/v1/uploads/{self.uid}/finish", headers=LOCAL).status_code, 200)
        for _ in range(240):
            meta = web.uploads.get(self.uid)
            if meta["status"] in ("ready", "failed"):
                break
            time.sleep(0.5)
        self.assertEqual(meta["status"], "ready", meta.get("error"))
        self.assertTrue(meta["title"].startswith("我的视频"))          # IMG_0001 becomes a friendly name
        self.assertEqual((meta["width"], meta["height"]), (720, 1280))  # rotation baked in, scaled to <=1280
        self.assertIn(self.uid, web.VIDEOS)
        listed = {v["id"]: v for v in self.client.get("/api/v1/videos", headers=LOCAL).json()}
        self.assertTrue(listed[self.uid]["vertical"])
        self.assertEqual(self.client.get(f"/api/v1/videos/{self.uid}/source", headers=LOCAL | {"range": "bytes=0-99"}).status_code, 206)

    def test_rejects_non_video(self):
        r = self.client.post("/api/v1/uploads", json={"name": "notes.txt", "size": 10}, headers=LOCAL)
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/uploads", json={"name": "big.mp4", "size": 5 * 1024 ** 3}, headers=LOCAL)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()

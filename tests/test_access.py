"""Open site with gated AI: free uses, name + approval, admin-only pages, private uploads."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from integrations import access, remote, uploads

try:
    from fastapi.testclient import TestClient
    import web.backend.app as web
    HAVE_APP = True
except Exception:  # pragma: no cover - optional deps
    HAVE_APP = False

LOCAL = {"host": "127.0.0.1:8765"}
PHONE = {"host": "abc.trycloudflare.com", "cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "203.0.113.9"}
OTHER = {"host": "abc.trycloudflare.com", "cf-connecting-ip": "198.51.100.7", "x-forwarded-for": "198.51.100.7"}


class AccessRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patch = mock.patch.multiple(access, SECRETS=self.tmp, VISITORS=self.tmp / "v.json", SETTINGS=self.tmp / "a.json")
        self.patch.start()
        access._ip_uses.clear(); access._ip_applies.clear()
        self.vid = access.visitor_id(access.new_token())

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_free_uses_then_name_then_approval(self):
        for i in range(6):
            self.assertEqual(access.use_ai(self.vid, "1.2.3.4")["left"], 5 - i)
        with self.assertRaises(access.Denied) as ctx:
            access.use_ai(self.vid, "1.2.3.4")
        self.assertEqual(ctx.exception.code, "AI_LOGIN_REQUIRED")
        self.assertEqual(access.apply(self.vid, " 张三 ", "红鸟", "1.2.3.4")["status"], "pending")
        with self.assertRaises(access.Denied) as ctx:
            access.use_ai(self.vid, "1.2.3.4")
        self.assertEqual(ctx.exception.code, "AI_PENDING")
        access.decide(self.vid, "approve")
        for _ in range(20):
            self.assertIsNone(access.use_ai(self.vid, "1.2.3.4")["left"])

    def test_rejected_and_revoked(self):
        access.apply(self.vid, "李四", "", "1.2.3.4")
        access.decide(self.vid, "reject")
        with self.assertRaises(access.Denied) as ctx:
            access.use_ai(self.vid, "1.2.3.4")
        self.assertEqual(ctx.exception.code, "AI_REJECTED")
        with self.assertRaises(ValueError):
            access.apply(self.vid, "李四", "", "1.2.3.4")
        access.decide(self.vid, "approve")
        access.decide(self.vid, "revoke")
        with self.assertRaises(access.Denied):
            access.use_ai(self.vid, "1.2.3.4")
        access.decide(self.vid, "reset")
        self.assertEqual(access.use_ai(self.vid, "1.2.3.4")["left"], 5)

    def test_one_network_cannot_farm_free_uses_with_new_cookies(self):
        access.update_settings({"ip_daily_free": 8})
        used = 0
        with self.assertRaises(access.Denied):
            for _ in range(20):
                access.use_ai(access.visitor_id(access.new_token()), "9.9.9.9"); used += 1
        self.assertEqual(used, 8)

    def test_names_are_cleaned_and_required(self):
        with self.assertRaises(ValueError):
            access.apply(self.vid, " a ", "", "1.2.3.4")
        rec = access.apply(self.vid, "<b>王五</b>\n", "x" * 200, "1.2.3.4")
        self.assertEqual(rec["name"], "b王五/b")
        self.assertEqual(len(access.listing()["visitors"][0]["note"]), 60)

    def test_bad_tokens_have_no_identity(self):
        self.assertIsNone(access.visitor_id("short"))
        self.assertIsNone(access.visitor_id("../../etc/passwd" * 3))


@unittest.skipUnless(HAVE_APP, "web app dependencies are unavailable")
class AccessGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.multiple(access, SECRETS=self.tmp, VISITORS=self.tmp / "v.json", SETTINGS=self.tmp / "a.json"),
            mock.patch.multiple(remote, SECRETS=self.tmp, CODE_FILE=self.tmp / "code", SESSIONS_FILE=self.tmp / "s.json",
                                LINK_FILE=self.tmp / "link", STATE_FILE=self.tmp / "cloudflared.json"),
        ]
        for p in self.patches:
            p.start()
        access._ip_uses.clear(); access._ip_applies.clear()
        self.phone = TestClient(web.app, base_url="https://abc.trycloudflare.com")
        self.other = TestClient(web.app, base_url="https://abc.trycloudflare.com")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_anyone_can_open_the_site_but_not_the_admin_page(self):
        r = self.phone.get("/app/index.html", headers=PHONE, follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn(access.COOKIE, r.cookies)
        self.assertEqual(self.phone.get("/api/v1/videos", headers=PHONE).status_code, 200)
        r = self.phone.get("/app/admin.html", headers=PHONE, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/app/login.html?admin=1"))
        for path in ("/api/v1/admin/visitors", "/api/v1/remote", "/api/v1/admin/site"):
            self.assertEqual(self.phone.get(path, headers=PHONE).status_code, 403, path)
        self.assertEqual(self.phone.post("/api/v1/admin/settings", json={"public": False}, headers=PHONE).status_code, 403)

    def test_owner_phone_session_can_use_admin(self):
        code = remote.access_code()
        self.phone.post("/api/v1/login", json={"code": code}, headers=PHONE)
        self.assertEqual(self.phone.get("/api/v1/admin/visitors", headers=PHONE).status_code, 200)
        self.assertTrue(self.phone.get("/api/v1/me", headers=PHONE).json()["admin"])

    def test_ai_chat_counts_then_asks_for_a_name(self):
        access.update_settings({"free_ai_uses": 2})
        with mock.patch.object(web, "ai_editor") as editor:
            editor.return_value.turn.return_value = {"reply": "好"}
            for _ in range(2):
                r = self.phone.post("/api/v1/chat", json={"message": "hi", "mode": "ai", "video_id": "cbf"}, headers=PHONE)
                self.assertEqual(r.status_code, 200)
            r = self.phone.post("/api/v1/chat", json={"message": "hi", "mode": "ai", "video_id": "cbf"}, headers=PHONE)
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (403, "AI_LOGIN_REQUIRED"))
        self.assertEqual(self.phone.get("/api/v1/me", headers=PHONE).json()["left"], 0)
        r = self.phone.post("/api/v1/access/apply", json={"name": "赵六", "note": "测试"}, headers=PHONE)
        self.assertEqual(r.json()["status"], "pending")
        listed = TestClient(web.app).get("/api/v1/admin/visitors", headers=LOCAL).json()
        self.assertEqual([v["name"] for v in listed["visitors"] if v["status"] == "pending"], ["赵六"])
        vid = listed["visitors"][0]["id"]
        TestClient(web.app).post(f"/api/v1/admin/visitors/{vid}", json={"action": "approve"}, headers=LOCAL)
        self.assertEqual(self.phone.get("/api/v1/me", headers=PHONE).json()["status"], "approved")

    def test_basic_edit_chat_is_free(self):
        access.update_settings({"free_ai_uses": 0})
        r = self.phone.post("/api/v1/chat", json={"message": "帮助", "mode": "lightweight", "video_id": "cbf"}, headers=PHONE)
        self.assertEqual(r.status_code, 200)

    def test_owner_is_never_limited(self):
        access.update_settings({"free_ai_uses": 0})
        with mock.patch.object(web, "ai_editor") as editor:
            editor.return_value.turn.return_value = {"reply": "好"}
            r = TestClient(web.app).post("/api/v1/chat", json={"message": "hi", "mode": "ai", "video_id": "cbf"}, headers=LOCAL)
        self.assertEqual(r.status_code, 200)

    def test_uploads_are_private_to_their_uploader(self):
        self.phone.get("/app/index.html", headers=PHONE)
        started = self.phone.post("/api/v1/uploads", json={"name": "a.mp4", "size": 100}, headers=PHONE).json()
        uid = started["id"]
        try:
            self.assertIsNotNone(uploads.get(uid)["owner"])
            self.assertIn(uid, [v["id"] for v in self.phone.get("/api/v1/videos", headers=PHONE).json()])
            self.other.get("/app/index.html", headers=OTHER)
            self.assertNotIn(uid, [v["id"] for v in self.other.get("/api/v1/videos", headers=OTHER).json()])
            self.assertEqual(self.other.get(f"/api/v1/uploads/{uid}", headers=OTHER).status_code, 404)
            self.assertEqual(self.other.delete(f"/api/v1/videos/{uid}", headers=OTHER).status_code, 404)
            self.assertIn(uid, [v["id"] for v in TestClient(web.app).get("/api/v1/videos", headers=LOCAL).json()])
            access.update_settings({"visitor_uploads": 1})
            r = self.phone.post("/api/v1/uploads", json={"name": "b.mp4", "size": 100}, headers=PHONE)
            self.assertEqual(r.status_code, 400)
        finally:
            uploads.delete(uid)

    def test_admin_site_has_its_own_address_and_qr_login(self):
        r = self.phone.get("/admin", headers=PHONE, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/app/login.html?admin=1"))
        token = remote.login_link_token()
        r = self.phone.get(f"/go/{token}?next=admin", headers=PHONE, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/admin"))
        self.assertEqual(self.phone.get("/admin", headers=PHONE).status_code, 200)
        site = self.phone.get("/api/v1/admin/site", headers=PHONE).json()
        self.assertNotIn("admin_qr", site)          # the login QR is never sent to a phone
        r = self.phone.get("/go/wrong-token-value-xxxxxxxx?next=admin", headers=PHONE, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/app/login.html?reset=1&admin=1")

    def test_signout_all_logs_phones_out(self):
        self.phone.get(f"/go/{remote.login_link_token()}?next=admin", headers=PHONE, follow_redirects=False)
        self.assertEqual(self.phone.post("/api/v1/admin/signout-all", headers=PHONE).status_code, 200)
        self.assertEqual(self.phone.get("/api/v1/admin/visitors", headers=PHONE).status_code, 403)

    def test_closed_site_still_needs_the_code(self):
        access.update_settings({"public": False})
        self.assertEqual(self.phone.get("/api/v1/videos", headers=PHONE).status_code, 401)


if __name__ == "__main__":
    unittest.main()

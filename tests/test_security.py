"""Security-focused unit tests for untrusted web/API input."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from integrations.api_config import resolve_base_url
from integrations.motrack_agent import validate_vision_event
from integrations.security import ensure_inside, session_directory, validate_session_id


class SecurityTests(unittest.TestCase):
    def test_session_id_accepts_generated_shapes(self):
        for value in ("lw-0123456789ab", "job-1a2b3c4d", "validation-doug", "a", "A" * 64):
            self.assertEqual(validate_session_id(value), value)

    def test_session_id_rejects_path_traversal(self):
        for value in ("../../etc/passwd", "..", ".", "", " ", "a/b", "a\\b", "a.b", "-leading",
                      "a" * 65, None):
            with self.assertRaises(ValueError, msg=repr(value)):
                validate_session_id(value)

    def test_session_id_trims_surrounding_whitespace(self):
        self.assertEqual(validate_session_id("  abc\n"), "abc")

    def test_session_directory_stays_under_root(self):
        root = Path("/srv/motrack")
        self.assertEqual(session_directory(root, root / "outputs", "abc"),
                         (root / "outputs" / "abc").resolve())
        for value in ("../../tmp/opencode/probe", "..", "a/b"):
            with self.assertRaises(ValueError):
                session_directory(root, root / "outputs", value)

    def test_ensure_inside_rejects_outside_and_symlink_escape(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            self.assertEqual(ensure_inside(root, root / "ok"), (root / "ok").resolve())
            with self.assertRaises(ValueError):
                ensure_inside(root, outside / "file")
            link = root / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks are not available")
            with self.assertRaises(ValueError):
                ensure_inside(root, link / "file")


class ApiConfigTests(unittest.TestCase):
    def test_https_is_accepted(self):
        with mock.patch.dict(os.environ, {"MOTRACK_API_BASE_URL": "https://api.example.com/v1"}, clear=False):
            self.assertEqual(resolve_base_url(), "https://api.example.com/v1")

    def test_loopback_http_is_accepted(self):
        for url in ("http://127.0.0.1:8000/v1", "http://localhost/v1", "http://[::1]:8000/v1"):
            with mock.patch.dict(os.environ, {"MOTRACK_API_BASE_URL": url}, clear=False):
                self.assertEqual(resolve_base_url(), url.rstrip("/"))

    def test_remote_http_requires_explicit_opt_in(self):
        env = {"MOTRACK_API_BASE_URL": "http://internal.example.com/v1"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MOTRACK_ALLOW_INSECURE_HTTP", None)
            with self.assertRaises(RuntimeError):
                resolve_base_url()
        with mock.patch.dict(os.environ, {**env, "MOTRACK_ALLOW_INSECURE_HTTP": "1"}, clear=False):
            with self.assertWarns(RuntimeWarning):
                self.assertEqual(resolve_base_url(), "http://internal.example.com/v1")

    def test_invalid_scheme_is_rejected(self):
        for url in ("ftp://example.com/v1", "not-a-url", ""):
            with mock.patch.dict(os.environ, {"MOTRACK_API_BASE_URL": url}, clear=False):
                if not url:
                    with mock.patch.dict(os.environ, {"MOTRACK_API_BASE_URL": ""}, clear=False):
                        with self.assertRaises(RuntimeError):
                            resolve_base_url()
                else:
                    with self.assertRaises(RuntimeError):
                        resolve_base_url()


class VisionValidationTests(unittest.TestCase):
    def test_clamps_window_and_confidence(self):
        event = validate_vision_event({"event_type": "shot_attempt", "start_time": -5, "end_time": 99,
                                       "confidence": 3, "evidence_frames": [1, 50, 200]}, 10, 20)
        self.assertEqual((event["start_time"], event["end_time"]), (10, 20))
        self.assertEqual(event["confidence"], 1.0)
        self.assertTrue(all(10 <= frame <= 20 for frame in event["evidence_frames"]))
        self.assertEqual(event["verification_status"], "MODEL_PREDICTED")

    def test_unknown_label_is_unverified_and_zero_length_is_widened(self):
        event = validate_vision_event({"event_type": "touchdown", "start_time": 12, "end_time": 12}, 10, 20)
        self.assertEqual(event["event_type"], "UNKNOWN")
        self.assertEqual(event["verification_status"], "UNVERIFIED")
        self.assertGreater(event["end_time"], event["start_time"])

    def test_swapped_timestamps_are_normalised(self):
        event = validate_vision_event({"event_type": "pass", "start_time": 8, "end_time": 6}, 5, 10)
        self.assertLess(event["start_time"], event["end_time"])

    def test_missing_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_vision_event({"event_type": "pass"}, 0, 10)

    def test_non_object_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_vision_event([], 0, 10)


if __name__ == "__main__":
    unittest.main()

"""
Integration tests for Meeting Notes API.
Run: python3 test_api.py

Starts the Flask server against a temp SQLite DB, exercises every feature,
then tears it down.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path

APP_DIR = Path(__file__).parent
TEST_PORT = 3459
BASE = f"http://localhost:{TEST_PORT}"

server_process = None


def api(path, method="GET", body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return resp.status, None
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None


def wait_for_server(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/api/meetings")
            return True
        except Exception:
            time.sleep(0.1)
    return False


class TestMeetingNotesAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        global server_process
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db", prefix="test-meetings-")
        os.close(cls.db_fd)
        # Remove so Flask/sqlite creates it fresh
        os.unlink(cls.db_path)

        env = os.environ.copy()
        env["DATABASE_PATH"] = cls.db_path
        env["PORT"] = str(TEST_PORT)

        server_process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=str(APP_DIR),
            env=env,
        )

        if not wait_for_server(timeout=10):
            server_process.kill()
            raise RuntimeError("Server failed to start")

    @classmethod
    def tearDownClass(cls):
        global server_process
        if server_process:
            server_process.terminate()
            server_process.wait(timeout=5)
        try:
            Path(cls.db_path).unlink(missing_ok=True)
        except Exception:
            pass

    # ── Feature 3: List all meetings ────────────────────────────────────────────

    def test_01_list_meetings_empty(self):
        status, body = api("/api/meetings")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 0)

    # ── Feature 1: Add a meeting ─────────────────────────────────────────────────

    def test_02_create_meeting(self):
        status, body = api("/api/meetings", "POST", {"title": "Kickoff", "date": "2026-04-01"})
        self.assertEqual(status, 201)
        self.assertEqual(body["title"], "Kickoff")
        self.assertEqual(body["date"], "2026-04-01")
        self.assertIn("id", body)

    def test_03_create_meeting_missing_title(self):
        status, _ = api("/api/meetings", "POST", {"date": "2026-04-01"})
        self.assertEqual(status, 400)

    def test_04_create_meeting_missing_date(self):
        status, _ = api("/api/meetings", "POST", {"title": "No Date"})
        self.assertEqual(status, 400)

    # ── Feature 2: Attach notes ──────────────────────────────────────────────────

    def test_05_add_note_to_meeting(self):
        _, meeting = api("/api/meetings", "POST", {"title": "Note Meeting", "date": "2026-04-10"})
        status, note = api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": "First point"})
        self.assertEqual(status, 201)
        self.assertEqual(note["content"], "First point")
        self.assertEqual(note["meetingId"], meeting["id"])

    def test_06_add_note_empty_content_rejected(self):
        _, meeting = api("/api/meetings", "POST", {"title": "Empty Note", "date": "2026-04-11"})
        status, _ = api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": ""})
        self.assertEqual(status, 400)

    # ── Feature 3: List with notes, ordered chronologically ─────────────────────

    def test_07_list_meetings_ordered_and_includes_notes(self):
        status, meetings = api("/api/meetings")
        self.assertEqual(status, 200)
        # Check ascending date order
        for i in range(1, len(meetings)):
            self.assertLessEqual(
                meetings[i - 1]["date"],
                meetings[i]["date"],
                f"Meetings not in date order at index {i}",
            )
        # Verify notes are embedded
        nm = next((m for m in meetings if m["title"] == "Note Meeting"), None)
        self.assertIsNotNone(nm)
        self.assertIsInstance(nm["notes"], list)
        self.assertEqual(len(nm["notes"]), 1)
        self.assertEqual(nm["notes"][0]["content"], "First point")

    # ── Feature 4: Search ────────────────────────────────────────────────────────

    def test_08_search_finds_matching_notes(self):
        _, meeting = api("/api/meetings", "POST", {"title": "Search Target", "date": "2026-05-01"})
        api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": "Quarterly revenue review"})
        api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": "Action: follow up on budget"})

        status, results = api("/api/search?q=revenue")
        self.assertEqual(status, 200)
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(all("revenue" in r["content"].lower() for r in results))

    def test_09_search_no_match_returns_empty(self):
        status, body = api("/api/search?q=xyzzy_no_match_abc123")
        self.assertEqual(status, 200)
        self.assertEqual(body, [])

    def test_10_search_empty_query_returns_empty(self):
        status, body = api("/api/search?q=")
        self.assertEqual(status, 200)
        self.assertEqual(body, [])

    # ── Feature 5: Delete note ───────────────────────────────────────────────────

    def test_11_delete_note_keeps_meeting(self):
        _, meeting = api("/api/meetings", "POST", {"title": "Del Note Mtg", "date": "2026-06-01"})
        _, note1 = api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": "Keep this"})
        _, note2 = api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": "Delete this"})

        status, _ = api(f"/api/notes/{note2['id']}", "DELETE")
        self.assertEqual(status, 204)

        _, meetings = api("/api/meetings")
        m = next((x for x in meetings if x["id"] == meeting["id"]), None)
        self.assertIsNotNone(m)
        self.assertEqual(len(m["notes"]), 1)
        self.assertEqual(m["notes"][0]["id"], note1["id"])

    # ── Feature 6: Footer ────────────────────────────────────────────────────────

    def test_13_html_has_footer(self):
        with urllib.request.urlopen(f"{BASE}/") as resp:
            html = resp.read().decode()
        self.assertIn("Made by AI ✨", html)

    # ── Feature 5: Delete meeting ────────────────────────────────────────────────

    def test_12_delete_meeting_removes_meeting_and_notes(self):
        _, meeting = api("/api/meetings", "POST", {"title": "Delete Me", "date": "2026-07-01"})
        api(f"/api/meetings/{meeting['id']}/notes", "POST", {"content": "Gone with the meeting"})

        status, _ = api(f"/api/meetings/{meeting['id']}", "DELETE")
        self.assertEqual(status, 204)

        _, meetings = api("/api/meetings")
        self.assertIsNone(next((m for m in meetings if m["id"] == meeting["id"]), None))


if __name__ == "__main__":
    unittest.main(verbosity=2)

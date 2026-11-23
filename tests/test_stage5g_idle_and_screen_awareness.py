"""
tests/test_stage5g_idle_and_screen_awareness.py - Test Suite for Stage 5G:
1. Sub-Millisecond Active-Window Awareness (tools/system.py)
2. Natural "Look at My Screen" Routing (brain/attachments.py & runtime_adapter.py)
3. Context-Gated Idle Follow-Ups (runtime_adapter.py)
"""

import os
import sys
import time
import json
import tempfile
import shutil
import unittest
from datetime import datetime, time as dt_time, timedelta
from unittest.mock import MagicMock, patch

_test_dir = tempfile.mkdtemp(prefix="orange_test_stage5g_")
os.environ["ORANGE_AI_USER_DATA_DIR"] = _test_dir
os.environ["ORANGE_ALLOWED_ROOTS"] = _test_dir
os.environ["ORANGE_API_KEY"] = ""

TAURI_DIR = r"D:\Orange AI\Orange AI Tauri"
DESKTOP_DIR = r"D:\Orange AI\Orange AI Desktop"
if TAURI_DIR not in sys.path:
    sys.path.insert(0, TAURI_DIR)
if DESKTOP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_DIR)

import runtime.runtime_adapter as ra
import main
import brain.memory as mem
from tools.system import classify_window_category, get_active_window_context
from brain.attachments import should_auto_capture_screen


class TestStage5GActiveWindowAwareness(unittest.TestCase):
    """Verifies sub-millisecond active window context sampling and deterministic categorization."""

    def test_01_classify_window_categories(self):
        """Verify deterministic category classification for IDEs, terminals, browsers, media, and general apps."""
        # Coding
        self.assertEqual(classify_window_category("Code.exe"), "coding")
        self.assertEqual(classify_window_category("cursor.exe"), "coding")
        self.assertEqual(classify_window_category("devenv.exe"), "coding")
        self.assertEqual(classify_window_category("idea64.exe"), "coding")
        self.assertEqual(classify_window_category("pycharm64.exe"), "coding")
        self.assertEqual(classify_window_category("antigravity.exe"), "coding")

        # Terminal
        self.assertEqual(classify_window_category("WindowsTerminal.exe"), "terminal")
        self.assertEqual(classify_window_category("wt.exe"), "terminal")
        self.assertEqual(classify_window_category("pwsh.exe"), "terminal")
        self.assertEqual(classify_window_category("powershell.exe"), "terminal")
        self.assertEqual(classify_window_category("cmd.exe"), "terminal")

        # Browser
        self.assertEqual(classify_window_category("chrome.exe"), "browser")
        self.assertEqual(classify_window_category("msedge.exe"), "browser")
        self.assertEqual(classify_window_category("brave.exe"), "browser")
        self.assertEqual(classify_window_category("firefox.exe"), "browser")

        # Media or Game
        self.assertEqual(classify_window_category("Spotify.exe"), "media_or_game")
        self.assertEqual(classify_window_category("vlc.exe"), "media_or_game")
        self.assertEqual(classify_window_category("mpv.exe"), "media_or_game")
        self.assertEqual(classify_window_category("steam.exe"), "media_or_game")
        self.assertEqual(classify_window_category("valorant.exe"), "media_or_game")

        # General
        self.assertEqual(classify_window_category("notepad.exe"), "general")
        self.assertEqual(classify_window_category("CalculatorApp.exe"), "general")
        self.assertEqual(classify_window_category(""), "general")

    def test_02_get_active_window_context_structure_and_fallback(self):
        """Verify get_active_window_context returns required dictionary keys safely."""
        ctx = get_active_window_context()
        self.assertIsInstance(ctx, dict)
        self.assertIn("process_name", ctx)
        self.assertIn("window_title", ctx)
        self.assertIn("category", ctx)
        self.assertIn("captured_at", ctx)
        self.assertIsInstance(ctx["captured_at"], float)
        self.assertIn(ctx["category"], ("coding", "terminal", "browser", "media_or_game", "general"))

    @patch("tools.system.psutil.Process")
    @patch("tools.system.ctypes.windll.user32")
    def test_03_get_active_window_context_mocked(self, mock_u32, mock_psutil_proc):
        """Verify mocked 64-bit safe ctypes Win32 calls extract context and classify properly."""
        mock_u32.GetForegroundWindow.return_value = 9876543210

        def fake_get_window_text(hwnd, buf, size):
            buf.value = "main.rs - Project - Visual Studio Code"
            return len(buf.value)

        mock_u32.GetWindowTextW.side_effect = fake_get_window_text

        def fake_get_pid(hwnd, p_pid):
            if hasattr(p_pid, "_obj"):
                p_pid._obj.value = 1234
            return 1

        mock_u32.GetWindowThreadProcessId.side_effect = fake_get_pid
        mock_proc = MagicMock()
        mock_proc.name.return_value = "Code.exe"
        mock_psutil_proc.return_value = mock_proc

        ctx = get_active_window_context()
        self.assertEqual(ctx["category"], "coding")
        self.assertEqual(ctx["process_name"], "Code.exe")
        self.assertEqual(ctx["window_title"], "main.rs - Project - Visual Studio Code")


class TestStage5GNaturalScreenRouting(unittest.TestCase):
    """Verifies natural language 'Look at My Screen' routing without Intent or ToolRegistry modifications."""

    def test_01_should_auto_capture_screen_triggers(self):
        """Verify explicit positive phrasing triggers screen capture."""
        positive_phrases = [
            "look at my screen",
            "Look at my screen please",
            "can you take a look at my screen",
            "check my screen",
            "Please check my screen and tell me what error is shown",
            "see my screen",
            "what's on my screen",
            "whats on my screen right now",
            "what is on my screen",
            "read my screen",
            "inspect my screen",
            "scan my screen for issues",
        ]
        for phrase in positive_phrases:
            self.assertTrue(should_auto_capture_screen(phrase), f"Expected True for '{phrase}'")

    def test_02_should_auto_capture_screen_negated(self):
        """Verify negated phrasing is rejected."""
        negated_phrases = [
            "don't look at my screen",
            "dont look at my screen",
            "do not look at my screen",
            "never check my screen",
            "stop looking at my screen",
            "don't scan my screen",
        ]
        for phrase in negated_phrases:
            self.assertFalse(should_auto_capture_screen(phrase), f"Expected False for '{phrase}'")

    def test_03_should_auto_capture_screen_general_phrases(self):
        """Verify general chat queries do not trigger screen capture."""
        general_phrases = [
            "hello",
            "open calculator",
            "how do I center a div in CSS?",
            "read file config.yaml",
            "run tests",
            "remind me in 10 minutes",
        ]
        for phrase in general_phrases:
            self.assertFalse(should_auto_capture_screen(phrase), f"Expected False for '{phrase}'")

    @patch("brain.attachments.capture_screen_attachment")
    def test_04_chat_send_auto_capture_screenshot(self, mock_capture):
        """Verify handle_chat_send automatically invokes capture_screen_attachment on screen triggers."""
        mock_capture.return_value = {
            "name": "screenshot-test.png",
            "kind": "screenshot",
            "mime_type": "image/png",
            "char_count": 150,
            "formatted_block": "```\n[SCREEN RESOLUTION: 1920x1080]\nOCR: Error in line 42\n```",
        }

        # Mock send_response
        responses = []
        with patch("runtime.runtime_adapter.send_response", side_effect=lambda req, res: responses.append((req, res))), \
             patch.object(main.api_client, "assist", return_value={"reply": "I see the error on your screen in line 42.", "model": "nvidia/nemotron-3.5-bolt-e4b"}):

            ra.handle_chat_send("req_test_screen", {"text": "What is on my screen?"})

            # Wait for background thread
            time.sleep(0.5)

            mock_capture.assert_called_once()
            self.assertEqual(len(responses), 1)
            req_id, outcome = responses[0]
            self.assertEqual(req_id, "req_test_screen")
            self.assertIn("attachments", outcome)
            self.assertEqual(len(outcome["attachments"]), 1)
            self.assertEqual(outcome["attachments"][0]["kind"], "screenshot")


class TestStage5GContextGatedIdleFollowups(unittest.TestCase):
    """Verifies 5-gate idle follow-up evaluator and anti-spam controls."""

    @classmethod
    def setUpClass(cls):
        ra._is_updating = False
        ra._is_shutting_down = False
        main.ensure_initialized()

    def setUp(self):
        ra._idle_nudge_sent_for_turn = False
        ra._last_activity_ts = None
        ra._session_conversational_state = None
        with ra._confirmations_lock:
            ra._pending_confirmations.clear()
        ra._latest_active_window = {
            "process_name": "Code.exe",
            "window_title": "app.py - VS Code",
            "category": "coding",
            "captured_at": time.time(),
        }

        # Configure settings
        ra.handle_settings_update({
            "settings": {
                "idle_followups_enabled": True,
                "idle_followup_minutes": 15,
                "active_window_awareness_enabled": True,
                "quiet_hours_enabled": False,
            }
        })

    def tearDown(self):
        ra._idle_nudge_sent_for_turn = False
        with ra._confirmations_lock:
            ra._pending_confirmations.clear()

    def _seed_turns(self, turns):
        """Helper to seed conversation_history for the current session."""
        settings = ra._load_gui_settings()
        start_id = int(settings.get("chat_session_start_id", 0) or 0)
        with mem.get_connection() as conn:
            for role, content in turns:
                conn.execute(
                    "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
                    (role, content, datetime.now().isoformat())
                )
            conn.commit()

    def test_01_idle_followup_fires_after_cooldown_on_question(self):
        """Idle follow-up fires when silence >= idle_followup_minutes and last assistant message has open question."""
        self._seed_turns([
            ("user", "Can you help me refactor this?"),
            ("assistant", "Sure! Would you like me to extract a separate helper module for that?"),
        ])

        # Elapsed silence: 16 minutes (cooldown is 15 minutes)
        ra._last_activity_ts = time.time() - (16 * 60)

        with patch.object(main.api_client, "assist", return_value={"reply": "Checking in—would you like me to proceed with extracting that module?"}):
            res = ra.evaluate_idle_followup()

            self.assertIsNotNone(res)
            self.assertTrue(res["success"])
            self.assertIn("extracting", res["reply"].lower())
            self.assertTrue(ra._idle_nudge_sent_for_turn)

    def test_02_idle_followup_blocks_duplicate_nudges_on_subsequent_ticks(self):
        """Once an idle follow-up fires, subsequent scheduler ticks stay silent for that turn."""
        self._seed_turns([
            ("user", "Let's check the database."),
            ("assistant", "Should I inspect the migrations table?"),
        ])
        ra._last_activity_ts = time.time() - (20 * 60)

        with patch.object(main.api_client, "assist", return_value={"reply": "Just checking in on the migrations table."}):
            # First tick fires
            res1 = ra.evaluate_idle_followup()
            self.assertIsNotNone(res1)
            self.assertTrue(ra._idle_nudge_sent_for_turn)

            # Second tick must return None
            res2 = ra.evaluate_idle_followup()
            self.assertIsNone(res2)

    def test_03_idle_followup_stays_silent_after_closed_action(self):
        """Idle follow-up stays silent after a completed, self-contained assistant turn."""
        self._seed_turns([
            ("user", "Close calculator"),
            ("assistant", "Closed 1 process(es) matching 'calculator'."),
        ])
        ra._last_activity_ts = time.time() - (20 * 60)

        res = ra.evaluate_idle_followup()
        self.assertIsNone(res, "Expected silent evaluation after self-contained completed action")

    def test_04_idle_followup_defers_during_media_or_game(self):
        """Idle follow-up defers when active window category is media_or_game."""
        self._seed_turns([
            ("user", "What should we do next?"),
            ("assistant", "Shall I run the test suite now?"),
        ])
        ra._last_activity_ts = time.time() - (20 * 60)
        ra._latest_active_window = {
            "process_name": "Spotify.exe",
            "window_title": "Spotify Premium",
            "category": "media_or_game",
            "captured_at": time.time(),
        }

        res = ra.evaluate_idle_followup()
        self.assertIsNone(res, "Expected follow-up to be deferred while user is listening to Spotify/gaming")

    def test_05_idle_followup_respects_quiet_hours(self):
        """Idle follow-up is suppressed inside configured quiet hours."""
        self._seed_turns([
            ("user", "Let's work on this"),
            ("assistant", "Would you like me to start?"),
        ])
        ra._last_activity_ts = time.time() - (20 * 60)

        ra.handle_settings_update({
            "settings": {
                "quiet_hours_enabled": True,
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
            }
        })

        # Test at 23:30 (inside quiet hours)
        quiet_now = datetime(2026, 11, 23, 23, 30, 0)
        res = ra.evaluate_idle_followup(now=quiet_now)
        self.assertIsNone(res, "Expected follow-up to be suppressed during quiet hours")

    def test_06_idle_followup_fires_on_pending_confirmation(self):
        """Idle follow-up fires when a confirmation is pending approval."""
        self._seed_turns([
            ("user", "Delete old temp log"),
            ("assistant", "Orange AI requests confirmation to delete 'temp.log'. Proceed? [y/N]"),
        ])
        with ra._confirmations_lock:
            ra._pending_confirmations["conf_1"] = {"tool": "delete_file"}
        ra._last_activity_ts = time.time() - (16 * 60)

        with patch.object(main.api_client, "assist", return_value={"reply": "Checking in—let me know if you want to proceed with deleting temp.log."}):
            res = ra.evaluate_idle_followup()
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])

    def test_07_idle_followup_fires_on_frustrated_session(self):
        """Idle follow-up fires when conversational state has unresolved friction."""
        self._seed_turns([
            ("user", "This syntax error won't go away!"),
            ("assistant", "Checking the traceback."),
        ])
        ra._session_conversational_state = {"emotional_tone": "frustrated", "cognitive_load": "high"}
        ra._last_activity_ts = time.time() - (16 * 60)

        with patch.object(main.api_client, "assist", return_value={"reply": "Checking in on this—let me know if you want to try an alternate fix."}):
            res = ra.evaluate_idle_followup()
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()

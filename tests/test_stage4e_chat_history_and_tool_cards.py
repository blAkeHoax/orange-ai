"""
tests/test_stage4e_chat_history_and_tool_cards.py - Integration & Regression Suite for Task 4E.

Validates:
1. chat.get_history Ordering on Large History (> 60 rows):
   - Confirms that chat.get_history(limit=10) returns the 10 MOST RECENT rows in chronological order (ascending IDs).
   - Guarantees restarts never load oldest legacy rows from the beginning of conversation_history.
2. chat.new_session Advances Watermark & Cleans Timeline:
   - Calling chat.new_session sets chat_session_start_id to MAX(id).
   - Subsequent chat.get_history returns empty until new turns are recorded.
   - Guarantees zero rows are deleted from conversation_history.
3. Structured Memory & Database Preservation:
   - Verifies structured_memories and legacy memories are 100% preserved when starting a new chat session.
4. SAFE Tool Output Text Population:
   - Verifies that executing a SAFE tool in process_user_turn populates non-empty textual output in tool_result
     (stdout, output, toolName, status="SUCCESS", commandArg), preventing "(Tool produced no textual output)".
5. Explicit Parameter Override:
   - Verifies that passing an explicit chat_session_start_id allows retrieving pre-watermark turns when needed.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Configure isolated environment
_test_dir = tempfile.mkdtemp(prefix="orange_test_stage4e_")
os.environ["ORANGE_AI_USER_DATA_DIR"] = _test_dir
os.environ["ORANGE_ALLOWED_ROOTS"] = f"{_test_dir}{os.pathsep}D:\\Orange AI"
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


class TestStage4EChatHistoryAndToolCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ra._is_updating = False
        ra._is_shutting_down = False
        main.ensure_initialized()

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp(prefix="orange_ws4e_")
        os.environ["ORANGE_ALLOWED_ROOTS"] = f"{_test_dir}{os.pathsep}{self.temp_workspace}{os.pathsep}D:\\Orange AI"
        # Reset settings to default before each test
        settings = ra._load_gui_settings()
        settings["chat_session_start_id"] = 0
        ra._save_gui_settings(settings)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _insert_dummy_turns(self, count=75):
        """Helper to insert sequential dummy conversation turns."""
        conn = mem.get_connection()
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn:
            for i in range(1, count + 1):
                role = "user" if i % 2 == 1 else "assistant"
                content = f"Turn content message #{i}"
                conn.execute(
                    "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
                    (role, content, now_iso),
                )

    def test_01_history_ordering_returns_most_recent_chronological(self):
        """When conversation_history has > 60 rows, chat.history returns the most recent turns in ascending order."""
        # Clean current table
        conn = mem.get_connection()
        with conn:
            conn.execute("DELETE FROM conversation_history")

        self._insert_dummy_turns(75)

        # Fetch latest 10 rows
        history = ra.handle_chat_history({"limit": 10})
        self.assertEqual(len(history), 10, f"Expected exactly 10 rows, got {len(history)}")

        # Verify turns are in ascending chronological order
        ids = [h["id"] for h in history]
        self.assertEqual(ids, sorted(ids), "Returned rows must be in ascending chronological order")

        # Verify they are the MOST RECENT 10 rows (i.e. ending in 75, not starting at 1)
        self.assertEqual(history[-1]["content"], "Turn content message #75")
        self.assertEqual(history[0]["content"], "Turn content message #66")
        self.assertNotIn("Turn content message #1", [h["content"] for h in history])

    def test_02_new_session_advances_watermark_and_cleans_timeline(self):
        """chat.new_session sets watermark to max(id), making subsequent history empty while preserving rows."""
        conn = mem.get_connection()
        with conn:
            conn.execute("DELETE FROM conversation_history")

        self._insert_dummy_turns(50)

        # Current history should return latest turns
        before_hist = ra.handle_chat_history({"limit": 20})
        self.assertEqual(len(before_hist), 20)

        # Trigger chat.new_session
        result = ra.handle_chat_new_session({})
        self.assertTrue(result.get("success"))
        self.assertGreaterEqual(result.get("chat_session_start_id"), 50)

        # Verify settings file updated
        settings = ra._load_gui_settings()
        self.assertEqual(settings.get("chat_session_start_id"), result["chat_session_start_id"])

        # Subsequent handle_chat_history should return empty
        after_hist = ra.handle_chat_history({"limit": 20})
        self.assertEqual(len(after_hist), 0, "Expected empty history after new_session watermark advancement")

        # Verify zero rows deleted from database
        cursor = conn.execute("SELECT COUNT(*) FROM conversation_history")
        total_count = cursor.fetchone()[0]
        self.assertEqual(total_count, 50, "Zero rows should be deleted from conversation_history")

        # Now add new turns in the new session
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute(
                "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
                ("user", "Fresh session message 1", now_iso),
            )
            conn.execute(
                "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
                ("assistant", "Fresh session reply 1", now_iso),
            )

        new_hist = ra.handle_chat_history({"limit": 20})
        self.assertEqual(len(new_hist), 2)
        self.assertEqual(new_hist[0]["content"], "Fresh session message 1")
        self.assertEqual(new_hist[1]["content"], "Fresh session reply 1")

    def test_03_structured_memory_intact_across_new_session(self):
        """Starting a new chat session preserves structured memory records completely."""
        # Create a structured memory record
        mem.remember_structured(
            category="project",
            key="current_task",
            value="Stage 4E Implementation",
        )

        initial_mems = mem.recall_structured()
        self.assertTrue(any(m.get("key") == "current_task" for m in initial_mems))

        # Advance session watermark
        res = ra.handle_chat_new_session({})
        self.assertTrue(res.get("success"))

        # Verify memory remains intact
        post_mems = mem.recall_structured()
        task_mem = next((m for m in post_mems if m.get("key") == "current_task"), None)
        self.assertIsNotNone(task_mem, "Structured memory must survive chat session reset")
        self.assertEqual(task_mem["value"], "Stage 4E Implementation")

    def test_04_safe_tool_execution_populates_tool_result_output(self):
        """Executing a SAFE tool in process_user_turn populates non-empty output text in tool_result."""
        test_file = os.path.join(self.temp_workspace, "sample_data.txt")
        file_payload = "Orange AI Stage 4E tool execution verified successfully.\nLine 2: Data item.\n"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(file_payload)

        # Mock LLM proposing read_file on test_file
        mock_reply = f'read_file(path="{test_file}")'
        with patch.object(main.api_client, "assist", return_value={"reply": mock_reply}):
            outcome = ra.process_user_turn(f'read_file(path="{test_file}")')

        self.assertIn("tool_result", outcome, "outcome must include 'tool_result' object")
        tr = outcome["tool_result"]
        self.assertEqual(tr.get("status"), "SUCCESS")
        self.assertEqual(tr.get("toolName"), "read_file")
        self.assertEqual(tr.get("tool"), "read_file")

        # Verify output/stdout fields are non-empty and reflect actual executed tool output
        self.assertTrue(len(tr.get("stdout", "")) > 0, "stdout in tool_result must not be empty")
        self.assertTrue(len(tr.get("output", "")) > 0, "output in tool_result must not be empty")
        self.assertIn("Stage 4E tool execution verified", tr["stdout"])
        self.assertEqual(tr["stdout"], tr["output"])
        self.assertIn(test_file, tr.get("commandArg", ""))

    def test_05_explicit_start_id_override_retrieves_past_turns(self):
        """Passing an explicit chat_session_start_id allows retrieving prior turns across watermarks."""
        conn = mem.get_connection()
        with conn:
            conn.execute("DELETE FROM conversation_history")
        self._insert_dummy_turns(30)

        # Advance session watermark
        ra.handle_chat_new_session({})

        # Default query returns empty
        default_hist = ra.handle_chat_history({"limit": 50})
        self.assertEqual(len(default_hist), 0)

        # Explicit override with chat_session_start_id=0 retrieves the historical turns
        override_hist = ra.handle_chat_history({"limit": 50, "chat_session_start_id": 0})
        self.assertEqual(len(override_hist), 30)
        self.assertEqual(override_hist[-1]["content"], "Turn content message #30")


if __name__ == "__main__":
    unittest.main()

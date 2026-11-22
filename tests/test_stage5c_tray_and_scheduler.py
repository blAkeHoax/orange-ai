"""
tests/test_stage5c_tray_and_scheduler.py - Stage 5C System Tray & Scheduler Heartbeat Test Suite.

Covers:
1. Settings persistence:
   - minimize_to_tray_enabled and desktop_toasts_enabled in settings.get and settings.update.
   - Non-boolean type rejection for tray and toast settings.
2. Scheduler heartbeat (run_scheduler_tick):
   - Triggers due Morning Briefing once per calendar day without duplicate runs.
3. Overdue reminder detection and events.ack deduplication:
   - Detects due reminder, inserts proactive event.
   - events.get_unacked returns it; events.ack marks it acknowledged.
   - Subsequent ticks do not duplicate the event.
4. Quiet-hours suppression gate:
   - Blocks/suppresses toasts when within quiet hours or when desktop_toasts_enabled is False.
   - Permits toasts outside quiet hours when desktop_toasts_enabled is True.
5. Fast thread termination:
   - SchedulerHeartbeat terminates cleanly in < 100ms upon shutdown signal.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Ensure bytecode is never written to disk
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["ORANGE_AI_TEST_MODE"] = "1"
os.environ["ORANGE_DISABLE_BACKGROUND_SCHEDULER"] = "1"

# Resolve and register workspace roots
_test_dir = os.path.dirname(os.path.abspath(__file__))
_tauri_root = os.path.dirname(_test_dir)
_desktop_root = os.path.join(os.path.dirname(_tauri_root), "Orange AI Desktop")
_runtime_dir = os.path.join(_tauri_root, "runtime")

os.environ["ORANGE_AI_DESKTOP_DIR"] = _desktop_root

if _desktop_root not in sys.path:
    sys.path.insert(0, _desktop_root)
if _runtime_dir not in sys.path:
    sys.path.insert(0, _runtime_dir)
if _tauri_root not in sys.path:
    sys.path.insert(0, _tauri_root)

import runtime_adapter
import main
import brain.memory as mem
import brain.reminders as rem_mod


class BaseStage5CIsolatedTest(unittest.TestCase):
    """Base test class providing temporary isolated environment."""

    def setUp(self):
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage5c_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        self._reset_engine_state()
        mem.initialize_memory()
        conn = mem.get_connection()
        rem_mod._init_db(conn)
        from brain.jobs.store import JobStore
        JobStore(os.path.join(self.temp_user_dir, "memory.db"))
        runtime_adapter._ensure_stage2c_tables()
        main.ensure_initialized()

    def tearDown(self):
        self._reset_engine_state()
        if self.orig_user_data_dir is not None:
            os.environ["ORANGE_AI_USER_DATA_DIR"] = self.orig_user_data_dir
        else:
            os.environ.pop("ORANGE_AI_USER_DATA_DIR", None)

        if os.path.exists(self.temp_user_dir):
            try:
                shutil.rmtree(self.temp_user_dir)
            except Exception:
                pass

    def _reset_engine_state(self):
        try:
            mem.close()
        except Exception:
            pass
        runtime_adapter._db_conn = None
        runtime_adapter.stop_scheduler_heartbeat(timeout=0.05)
        if hasattr(main, "reset_session"):
            main.reset_session()
        main.history = []


class TestStage5CTrayAndScheduler(BaseStage5CIsolatedTest):

    def test_01_settings_persistence(self):
        """minimize_to_tray_enabled and desktop_toasts_enabled persist and validate booleans."""
        get_res = runtime_adapter.handle_settings_get({})
        self.assertIn("minimize_to_tray_enabled", get_res)
        self.assertIn("desktop_toasts_enabled", get_res)
        self.assertTrue(get_res["minimize_to_tray_enabled"])
        self.assertTrue(get_res["desktop_toasts_enabled"])

        # Update to False
        up_res = runtime_adapter.handle_settings_update({
            "settings": {
                "minimize_to_tray_enabled": False,
                "desktop_toasts_enabled": False,
            }
        })
        self.assertTrue(up_res.get("success"))
        self.assertFalse(up_res["settings"]["minimize_to_tray_enabled"])
        self.assertFalse(up_res["settings"]["desktop_toasts_enabled"])

        # Verify persisted via get
        re_get = runtime_adapter.handle_settings_get({})
        self.assertFalse(re_get["minimize_to_tray_enabled"])
        self.assertFalse(re_get["desktop_toasts_enabled"])

        # Reject non-booleans
        bad_res1 = runtime_adapter.handle_settings_update({
            "settings": {"minimize_to_tray_enabled": "true"}
        })
        self.assertFalse(bad_res1.get("success"))
        self.assertIn("minimize_to_tray_enabled must be a boolean", bad_res1.get("error", ""))

        bad_res2 = runtime_adapter.handle_settings_update({
            "settings": {"desktop_toasts_enabled": 1}
        })
        self.assertFalse(bad_res2.get("success"))
        self.assertIn("desktop_toasts_enabled must be a boolean", bad_res2.get("error", ""))

    def test_02_scheduler_tick_briefing_once_per_day(self):
        """run_scheduler_tick generates due Morning Briefing exactly once per calendar day without duplication."""
        runtime_adapter.handle_settings_update({
            "settings": {
                "morning_briefing_enabled": True,
                "preferred_briefing_time": "08:00",
                "quiet_hours_enabled": False,
            }
        })

        test_now_1 = datetime(2026, 11, 22, 9, 0, 0)
        with patch.object(main.api_client, "assist") as mock_assist:
            mock_assist.return_value = {
                "reply": "Good morning! Here is your daily overview.",
                "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
            }

            # First tick: should generate briefing
            tick_1 = runtime_adapter.run_scheduler_tick(now=test_now_1)
            self.assertTrue(tick_1["briefing_generated"])
            self.assertIsNotNone(tick_1["briefing"])

            # Verify briefing recorded in database
            conn = mem.get_connection()
            cur = conn.execute("SELECT id, local_date, status FROM daily_briefings WHERE local_date = '2026-11-22'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "2026-11-22")

            # Second tick (same day, 30 seconds later): must NOT generate duplicate briefing
            test_now_2 = datetime(2026, 11, 22, 9, 0, 30)
            tick_2 = runtime_adapter.run_scheduler_tick(now=test_now_2)
            self.assertFalse(tick_2["briefing_generated"])
            self.assertIsNone(tick_2["briefing"])

    def test_03_overdue_reminder_detection_and_ack_deduplication(self):
        """Overdue reminders trigger proactive events, which are deduplicated and acknowledged via events.ack."""
        conn = mem.get_connection()
        conn.execute(
            "INSERT INTO reminders (message, due_at, created_at, fired) VALUES (?, ?, ?, 0)",
            ("Review architecture diagram", "2026-11-22 08:30:00", "2026-11-22 08:00:00")
        )
        conn.commit()
        rem_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Tick at 09:00: reminder is overdue
        test_now_1 = datetime(2026, 11, 22, 9, 0, 0)
        tick_1 = runtime_adapter.run_scheduler_tick(now=test_now_1)
        self.assertGreaterEqual(tick_1["reminders_count"], 1)

        # Check unacknowledged events
        unacked = runtime_adapter.handle_events_get_unacked({})
        matching = [e for e in unacked if str(e.get("entity_id")) == str(rem_id)]
        self.assertEqual(len(matching), 1)
        evt_id = matching[0]["event_id"]

        # Acknowledge the event
        ack_res = runtime_adapter.handle_events_ack({"event_id": evt_id})
        self.assertTrue(ack_res.get("acknowledged"))

        # Re-fetch unacknowledged: should no longer contain this event
        unacked_after = runtime_adapter.handle_events_get_unacked({})
        matching_after = [e for e in unacked_after if e.get("event_id") == evt_id]
        self.assertEqual(len(matching_after), 0)

        # Second tick: should not re-emit duplicate event
        tick_2 = runtime_adapter.run_scheduler_tick(now=datetime(2026, 11, 22, 9, 0, 30))
        self.assertEqual(tick_2["reminders_count"], 0)

    def test_04_quiet_hours_suppression_gate(self):
        """run_scheduler_tick suppresses toasts during quiet hours or when desktop_toasts_enabled is False."""
        runtime_adapter.handle_settings_update({
            "settings": {
                "quiet_hours_enabled": True,
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
                "desktop_toasts_enabled": True,
            }
        })

        # Inside quiet hours (23:30)
        night_tick = runtime_adapter.run_scheduler_tick(now=datetime(2026, 11, 22, 23, 30, 0))
        self.assertTrue(night_tick["quiet_hours"])
        self.assertTrue(night_tick["suppress_toast"])

        # Outside quiet hours (14:00) with desktop_toasts_enabled=True
        day_tick = runtime_adapter.run_scheduler_tick(now=datetime(2026, 11, 22, 14, 0, 0))
        self.assertFalse(day_tick["quiet_hours"])
        self.assertFalse(day_tick["suppress_toast"])

        # Outside quiet hours (14:00) with desktop_toasts_enabled=False
        runtime_adapter.handle_settings_update({
            "settings": {"desktop_toasts_enabled": False}
        })
        disabled_tick = runtime_adapter.run_scheduler_tick(now=datetime(2026, 11, 22, 14, 0, 0))
        self.assertFalse(disabled_tick["quiet_hours"])
        self.assertTrue(disabled_tick["suppress_toast"])

    def test_05_clean_thread_shutdown_under_100ms(self):
        """SchedulerHeartbeat background thread terminates in < 100ms upon shutdown signal."""
        # Enable scheduler temporarily for this test
        old_env = os.environ.get("ORANGE_DISABLE_BACKGROUND_SCHEDULER")
        try:
            os.environ["ORANGE_DISABLE_BACKGROUND_SCHEDULER"] = "0"
            runtime_adapter.init_scheduler_heartbeat()
            self.assertIsNotNone(runtime_adapter._scheduler_heartbeat_thread)
            self.assertTrue(runtime_adapter._scheduler_heartbeat_thread.is_alive())

            # Measure termination latency
            start_t = time.perf_counter()
            runtime_adapter.stop_scheduler_heartbeat(timeout=0.05)
            elapsed = time.perf_counter() - start_t

            self.assertLess(elapsed, 0.1, f"Thread shutdown took {elapsed:.4f}s, exceeding 100ms ceiling")
            self.assertTrue(
                runtime_adapter._scheduler_heartbeat_thread is None
                or not runtime_adapter._scheduler_heartbeat_thread.is_alive()
            )
        finally:
            if old_env is not None:
                os.environ["ORANGE_DISABLE_BACKGROUND_SCHEDULER"] = old_env
            else:
                os.environ.pop("ORANGE_DISABLE_BACKGROUND_SCHEDULER", None)


if __name__ == "__main__":
    unittest.main()

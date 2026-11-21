"""
tests/test_stage4_proactive_reliability.py - Stage 4 Proactive Reliability Integration Test Suite.

Validates Stage 4 proactive engine hardening:
1. No Reminder Swallowing Under Concurrent Loops (GAP-4A-1):
   - Verifies that SchedulerLoop with on_reminder_due=None does NOT touch due reminders or mark them fired.
   - Verifies that Stage2CBackgroundWorker._check_and_emit_due_reminders() is the sole authoritative
     code path that queries get_due_reminders(), writes to proactive_events, emits "reminder.due",
     and marks fired = 1.
   - Verifies that fired = 1 is ONLY set after proactive_events record is verified persisted.
2. Non-Blocking Reminder Delivery During Slow Briefing Synthesis (GAP-4A-2):
   - Simulates a slow briefing synthesis network call.
   - Verifies _evaluate_morning_briefing(sync=False) returns immediately without blocking.
   - Verifies _briefing_eval_in_flight prevents duplicate synthesis threads from spawning.
   - Verifies due reminders are evaluated and delivered without delay while synthesis is in flight.
3. Manual Briefing Trigger RPC (GAP-4A-3 & METHOD_REGISTRY):
   - Verifies stage2c.trigger_briefing and briefing.trigger RPC handlers execute atomic synthesis.
   - Verifies daily_briefings + proactive_events persistence and "briefing.ready" event emission.
4. Clean Worker Shutdown:
   - Verifies _stop_stage2c_background_workers(timeout=3.0) joins worker, reconciliation,
     and briefing synthesis threads with zero lingering threads.
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Ensure bytecode is never written to disk
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["ORANGE_AI_TEST_MODE"] = "1"

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

import runtime_adapter as ra
import main
import brain.memory as mem
from brain import scheduler
from brain.reminders import add_reminder, get_due_reminders, mark_fired


class TestStage4ProactiveReliability(unittest.TestCase):
    """Stage 4 Proactive Delivery Hardening and Engine Reliability Tests."""

    def setUp(self):
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage4_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        self._reset_engine_state()

        # Initialize isolated schema
        mem.initialize_memory()
        ra._ensure_stage2c_tables()
        main.ensure_initialized()

        self.db_path = os.path.join(self.temp_user_dir, "memory.db")

        # Write default settings with morning briefing enabled
        settings_path = os.path.join(self.temp_user_dir, "settings.json")
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump({
                "morning_briefing_enabled": True,
                "preferred_briefing_time": "08:30",
                "contextual_advisories_enabled": True,
                "advisory_cooldown_hours": 4,
            }, f)

        # Clear in-flight briefing flags
        with ra._briefing_eval_lock:
            ra._briefing_eval_in_flight = False
        ra._briefing_worker_thread = None

    def tearDown(self):
        # Stop any active workers cleanly
        try:
            ra._stop_stage2c_background_workers(timeout=2.0)
        except Exception:
            pass
        try:
            scheduler.stop(wait_timeout=2.0)
        except Exception:
            pass

        self._reset_engine_state()

        # Reset in-flight state
        with ra._briefing_eval_lock:
            ra._briefing_eval_in_flight = False
        ra._briefing_worker_thread = None

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
        ra._db_conn = None

    def test_no_reminder_swallowing_under_concurrent_loops(self):
        """
        GAP-4A-1 Verification:
        When SchedulerLoop runs with on_reminder_due=None alongside Stage2CBackgroundWorker:
        1. SchedulerLoop.check_once() does NOT mark reminders fired or emit scheduler.reminder_due.
        2. Stage2CBackgroundWorker._check_and_emit_due_reminders() persists reminder.due in
           proactive_events, emits reminder.due, and marks fired=1.
        3. No reminders are swallowed or lost.
        """
        # 1. Insert a due reminder using add_reminder
        past_dt = datetime.now() - timedelta(minutes=5)
        rem_id = add_reminder("Review pull request #10", past_dt)

        emitted_events = []

        def mock_send_event(event_name, payload):
            emitted_events.append((event_name, payload))

        with patch.object(ra, "send_event", side_effect=mock_send_event):
            # 2. Simulate SchedulerLoop tick (which in Tauri mode runs with on_reminder_due=None)
            scheduler.check_once(on_reminder_due=None)

            # Verify SchedulerLoop did NOT touch the reminder
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
                fired_val = cur.fetchone()[0]
                self.assertEqual(fired_val, 0, "SchedulerLoop must NOT mark reminder as fired when on_reminder_due is None")

            # Verify no scheduler.reminder_due event was emitted
            scheduler_events = [e for e in emitted_events if e[0] == "scheduler.reminder_due"]
            self.assertEqual(len(scheduler_events), 0, "SchedulerLoop must NOT emit scheduler.reminder_due")

            # 3. Simulate Stage2CBackgroundWorker reminder check
            ra._check_and_emit_due_reminders()

            # Verify Stage2CBackgroundWorker persisted the event in proactive_events
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_type, entity_id FROM proactive_events WHERE entity_id = ?", (str(rem_id),))
                evt_row = cur.fetchone()
                self.assertIsNotNone(evt_row, "proactive_events must contain the emitted reminder envelope")
                self.assertEqual(evt_row[0], "reminder.due")

                # Verify reminders table is now marked fired = 1
                cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
                fired_after = cur.fetchone()[0]
                self.assertEqual(fired_after, 1, "Stage2CBackgroundWorker must mark reminder fired = 1 after persisting")

            # Verify authoritative "reminder.due" was emitted over stdio transport
            reminder_events = [e for e in emitted_events if e[0] == "reminder.due"]
            self.assertEqual(len(reminder_events), 1, "Exactly one reminder.due event must be emitted")
            self.assertEqual(reminder_events[0][1]["payload"]["reminder_id"], rem_id)

            # 4. Subsequent passes must not duplicate emission or re-fire
            ra._check_and_emit_due_reminders()
            scheduler.check_once(on_reminder_due=None)
            reminder_events_after = [e for e in emitted_events if e[0] == "reminder.due"]
            self.assertEqual(len(reminder_events_after), 1, "Subsequent check passes must not duplicate emission")

    def test_reminder_only_marked_fired_after_persisted(self):
        """
        Verify that mark_fired is strictly conditional upon verified persistence in proactive_events.
        """
        past_dt = datetime.now() - timedelta(minutes=5)
        rem_id = add_reminder("Database crash test reminder", past_dt)

        # Simulate failure inside emit_proactive_event so proactive_events is NOT written
        with patch.object(ra, "emit_proactive_event", return_value=None):
            with patch.object(ra, "_get_db_connection", side_effect=sqlite3.OperationalError("Simulated DB lock")):
                ra._check_and_emit_due_reminders()

        # Verify reminder was NOT marked fired
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
            fired_val = cur.fetchone()[0]
            self.assertEqual(fired_val, 0, "Reminder must remain fired = 0 if proactive event persistence fails")

    def test_non_blocking_reminder_delivery_during_slow_briefing(self):
        """
        GAP-4A-2 Verification:
        A slow morning briefing synthesis running in the background:
        1. Runs asynchronously without blocking the calling thread.
        2. Guards against concurrent duplicate synthesis threads.
        3. Allows due reminders to be checked and delivered immediately.
        """
        synthesis_started = threading.Event()
        synthesis_release = threading.Event()

        def slow_synthesize(context, timeout=60.0):
            synthesis_started.set()
            # Wait until test releases or timeout after 5s
            synthesis_release.wait(timeout=5.0)
            mock_briefing = MagicMock()
            mock_briefing.is_fallback = False
            mock_briefing.summary_markdown = "# Simulated Async Briefing\n\nAll tasks running."
            mock_briefing.model_name = "nvidia/nemotron-3.5-lightning-30b-a3b"
            mock_briefing.priorities = []
            return mock_briefing

        with patch("runtime_adapter.BriefingSynthesizer") as mock_synth_cls:
            synth_instance = mock_synth_cls.return_value
            synth_instance.synthesize.side_effect = slow_synthesize

            # 1. Trigger non-blocking briefing synthesis
            res = ra._evaluate_morning_briefing(force=True, sync=False)
            self.assertIsNotNone(res)
            self.assertEqual(res.get("status"), "in_flight", "Non-blocking briefing evaluation must return in_flight status")

            # Wait for synthesis thread to enter execution
            started = synthesis_started.wait(timeout=3.0)
            self.assertTrue(started, "Briefing synthesis thread must start execution")

            # 2. Verify in-flight guard prevents duplicate run
            with ra._briefing_eval_lock:
                in_flight_status = ra._briefing_eval_in_flight
            self.assertTrue(in_flight_status, "_briefing_eval_in_flight must be True while synthesis runs")

            duplicate_res = ra._evaluate_morning_briefing(force=True, sync=False)
            self.assertIsNone(duplicate_res, "Subsequent evaluation call while in-flight must be skipped (return None)")

            # 3. Verify due reminder check executes immediately while briefing is still running
            past_dt = datetime.now() - timedelta(minutes=2)
            rem_id = add_reminder("Urgent non-blocked reminder", past_dt)

            start_t = time.time()
            ra._check_and_emit_due_reminders()
            duration = time.time() - start_t

            self.assertLess(duration, 0.5, "Due reminders check must execute immediately without waiting for briefing synthesis")

            # Verify reminder was persisted and fired
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
                self.assertEqual(cur.fetchone()[0], 1)

            # 4. Release slow synthesis and let it complete cleanly
            synthesis_release.set()
            if ra._briefing_worker_thread:
                ra._briefing_worker_thread.join(timeout=3.0)

            # Verify in-flight flag reset
            with ra._briefing_eval_lock:
                in_flight_after = ra._briefing_eval_in_flight
            self.assertFalse(in_flight_after, "_briefing_eval_in_flight must reset to False after thread finishes")

            # Verify briefing was persisted in daily_briefings and proactive_events
            today_str = datetime.now().strftime("%Y-%m-%d")
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT local_date, status FROM daily_briefings WHERE local_date = ?", (today_str,))
                row = cur.fetchone()
                self.assertIsNotNone(row, "daily_briefings must contain the synthesized record")
                self.assertEqual(row[1], "success")

    def test_manual_briefing_trigger_rpc(self):
        """
        GAP-4A-3 Verification:
        Verify stage2c.trigger_briefing and briefing.trigger RPC endpoints in METHOD_REGISTRY.
        """
        self.assertIn("stage2c.trigger_briefing", ra.METHOD_REGISTRY, "stage2c.trigger_briefing must be in METHOD_REGISTRY")
        self.assertIn("briefing.trigger", ra.METHOD_REGISTRY, "briefing.trigger must be in METHOD_REGISTRY")

        mock_briefing = MagicMock()
        mock_briefing.is_fallback = False
        mock_briefing.summary_markdown = "# Manual Trigger Briefing\n\nGenerated on demand."
        mock_briefing.model_name = "nvidia/nemotron-3.5-lightning-30b-a3b"
        mock_briefing.priorities = []

        emitted = []

        def mock_send(evt_name, payload):
            emitted.append((evt_name, payload))

        with patch("runtime_adapter.BriefingSynthesizer") as mock_synth_cls:
            synth_instance = mock_synth_cls.return_value
            synth_instance.synthesize.return_value = mock_briefing

            with patch.object(ra, "send_event", side_effect=mock_send):
                res = ra.handle_stage2c_trigger_briefing({"force": True, "sync": True})
                self.assertTrue(res.get("success"), "Manual trigger RPC must return success: True")
                self.assertIsNotNone(res.get("briefing"))
                self.assertEqual(res["briefing"]["status"], "success")

                # Verify proactive event was emitted
                briefing_events = [e for e in emitted if e[0] == "briefing.ready"]
                self.assertEqual(len(briefing_events), 1, "Exactly one briefing.ready event must be emitted")

                # Verify database atomic persistence
                today_str = datetime.now().strftime("%Y-%m-%d")
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM daily_briefings WHERE local_date = ?", (today_str,))
                    self.assertIsNotNone(cur.fetchone())

                    cur.execute("SELECT event_id FROM proactive_events WHERE event_type = 'briefing.ready'")
                    self.assertIsNotNone(cur.fetchone())

    def test_clean_worker_shutdown(self):
        """
        Verify that _stop_stage2c_background_workers terminates all background threads cleanly.
        """
        ra._init_stage2c_background_workers()

        self.assertIsNotNone(ra._stage2c_worker_thread)
        self.assertTrue(ra._stage2c_worker_thread.is_alive())

        # Trigger clean stop
        ra._stop_stage2c_background_workers(timeout=3.0)

        self.assertFalse(ra._stage2c_worker_thread.is_alive(), "Worker thread must terminate cleanly")
        if ra._stage2c_reconciliation_thread:
            self.assertFalse(ra._stage2c_reconciliation_thread.is_alive(), "Reconciliation thread must terminate cleanly")
        if ra._briefing_worker_thread:
            self.assertFalse(ra._briefing_worker_thread.is_alive(), "Briefing synthesis thread must terminate cleanly")


if __name__ == "__main__":
    unittest.main()

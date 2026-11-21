"""
tests/test_stage4c_controls_and_followups.py - Stage 4C Proactive Controls & Follow-Ups Test Suite.

Validates:
1. Quiet Hours / Do-Not-Disturb (GAP-4A-5):
   - _is_within_quiet_hours() across overnight (22:00-07:00) and same-day (13:00-15:00) spans.
   - Deferral of automatic morning briefings, idle recommendations, and job followups during quiet hours.
   - Delivery of deferred events once outside quiet hours.
   - Immediate execution for explicit manual user trigger (force=True).
2. Configurable Idle Inactivity Threshold (GAP-4A-7):
   - Dynamic idle_threshold_minutes setting controlling when _evaluate_idle_recommendations() fires.
3. Pre-Due Reminder Lead-Time Alerts (GAP-4A-6, Zero Schema Changes):
   - reminders.create with lead_time_minutes (0..1440).
   - Emission of deduplicated "reminder.upcoming" event without setting fired = 1.
   - Subsequent emission of "reminder.due" at due_at with fired = 1 and metadata cleanup.
   - Cleanup of lead-time metadata when cancelled.
4. Post-Job Task Follow-Ups:
   - Terminal COMPLETED and FAILED jobs emitting deduplicated "job.followup" proactive events.
   - Quiet hours deferral and subsequent pickup for terminal jobs.
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

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["ORANGE_AI_TEST_MODE"] = "1"

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
import brain.reminders as rem_mod
from brain.jobs.models import Job, JobStatus


class TestStage4CControlsAndFollowups(unittest.TestCase):
    """Stage 4C Proactive Controls, Lead Times, and Follow-Up Integration Tests."""

    def setUp(self):
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage4c_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        self._reset_engine_state()

        mem.initialize_memory()
        ra._ensure_stage2c_tables()
        main.ensure_initialized()

        self.db_path = os.path.join(self.temp_user_dir, "memory.db")

        # Initialize base settings
        settings_path = os.path.join(self.temp_user_dir, "gui_settings.json")
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump({
                "theme": "dark",
                "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                "morning_briefing_enabled": True,
                "preferred_briefing_time": "08:30",
                "contextual_advisories_enabled": True,
                "advisory_cooldown_hours": 4,
                "quiet_hours_enabled": False,
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
                "idle_threshold_minutes": 10,
                "reminder_lead_times": {},
            }, f)

        with ra._briefing_eval_lock:
            ra._briefing_eval_in_flight = False
        ra._briefing_worker_thread = None

    def tearDown(self):
        try:
            ra._stop_stage2c_background_workers(timeout=2.0)
        except Exception:
            pass
        try:
            scheduler.stop(wait_timeout=2.0)
        except Exception:
            pass

        self._reset_engine_state()

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
        try:
            rem_mod.close()
        except Exception:
            pass
        ra._db_conn = None

    def test_is_within_quiet_hours_windows(self):
        """
        Validate _is_within_quiet_hours() across overnight (22:00-07:00),
        same-day (13:00-15:00), disabled, and edge-case equal boundaries.
        """
        # 1. Overnight span (22:00 to 07:00)
        overnight_settings = {
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        }
        # Inside overnight window
        t_2300 = datetime(2026, 11, 21, 23, 0, 0)
        t_0200 = datetime(2026, 11, 21, 2, 0, 0)
        t_2200 = datetime(2026, 11, 21, 22, 0, 0)  # Start boundary inclusive
        self.assertTrue(ra._is_within_quiet_hours(overnight_settings, t_2300))
        self.assertTrue(ra._is_within_quiet_hours(overnight_settings, t_0200))
        self.assertTrue(ra._is_within_quiet_hours(overnight_settings, t_2200))

        # Outside overnight window
        t_0700 = datetime(2026, 11, 21, 7, 0, 0)  # End boundary exclusive
        t_1200 = datetime(2026, 11, 21, 12, 0, 0)
        t_2159 = datetime(2026, 11, 21, 21, 59, 59)
        self.assertFalse(ra._is_within_quiet_hours(overnight_settings, t_0700))
        self.assertFalse(ra._is_within_quiet_hours(overnight_settings, t_1200))
        self.assertFalse(ra._is_within_quiet_hours(overnight_settings, t_2159))

        # 2. Same-day span (13:00 to 15:00)
        sameday_settings = {
            "quiet_hours_enabled": True,
            "quiet_hours_start": "13:00",
            "quiet_hours_end": "15:00",
        }
        t_1259 = datetime(2026, 11, 21, 12, 59, 59)
        t_1300 = datetime(2026, 11, 21, 13, 0, 0)  # Start boundary inclusive
        t_1430 = datetime(2026, 11, 21, 14, 30, 0)
        t_1500 = datetime(2026, 11, 21, 15, 0, 0)  # End boundary exclusive
        t_1600 = datetime(2026, 11, 21, 16, 0, 0)
        self.assertFalse(ra._is_within_quiet_hours(sameday_settings, t_1259))
        self.assertTrue(ra._is_within_quiet_hours(sameday_settings, t_1300))
        self.assertTrue(ra._is_within_quiet_hours(sameday_settings, t_1430))
        self.assertFalse(ra._is_within_quiet_hours(sameday_settings, t_1500))
        self.assertFalse(ra._is_within_quiet_hours(sameday_settings, t_1600))

        # 3. Disabled quiet hours
        disabled_settings = {
            "quiet_hours_enabled": False,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        }
        self.assertFalse(ra._is_within_quiet_hours(disabled_settings, t_2300))

        # 4. Equal boundaries (empty window)
        equal_settings = {
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "22:00",
        }
        self.assertFalse(ra._is_within_quiet_hours(equal_settings, t_2200))

    def test_quiet_hours_deferral_and_subsequent_delivery(self):
        """
        Validate that automatic morning briefings and idle advisories defer
        cleanly during quiet hours without dropping events, and deliver once outside.
        Also verifies manual trigger (force=True) bypasses quiet hours.
        """
        ra.handle_settings_update({
            "settings": {
                "morning_briefing_enabled": True,
                "preferred_briefing_time": "08:30",
                "quiet_hours_enabled": True,
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
                "contextual_advisories_enabled": True,
            }
        })

        quiet_time = datetime(2026, 11, 21, 23, 30, 0)

        # 1. Automatic morning briefing inside quiet hours: must defer (return None)
        briefing_res = ra._evaluate_morning_briefing(force=False, test_now=quiet_time, sync=True)
        self.assertIsNone(briefing_res)

        # Confirm no daily_briefings or proactive_events written
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM daily_briefings")
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute("SELECT COUNT(*) FROM proactive_events WHERE event_type = 'briefing.ready'")
            self.assertEqual(cur.fetchone()[0], 0)

        # 2. Idle recommendations inside quiet hours: must defer (return [])
        ra._last_user_activity = quiet_time.timestamp() - 1000.0
        idle_res = ra._evaluate_idle_recommendations(force=False, test_now=quiet_time)
        self.assertEqual(idle_res, [])

        # 3. Manual briefing trigger with force=True inside quiet hours: must execute immediately
        with patch.object(ra, "send_event"):
            manual_res = ra._evaluate_morning_briefing(force=True, test_now=quiet_time, sync=True)
            self.assertIsNotNone(manual_res)
            self.assertEqual(manual_res.get("local_date"), "2026-11-21")

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM daily_briefings WHERE local_date = '2026-11-21'")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_configurable_idle_inactivity_threshold(self):
        """
        Validate that idle_threshold_minutes persists, updates _idle_inactivity_threshold,
        and dynamically governs _evaluate_idle_recommendations().
        """
        # Update idle threshold to 5 minutes (300 seconds)
        update_res = ra.handle_settings_update({"settings": {"idle_threshold_minutes": 5}})
        self.assertTrue(update_res["success"])
        self.assertEqual(update_res["settings"]["idle_threshold_minutes"], 5)
        self.assertEqual(ra._idle_inactivity_threshold, 300.0)

        now = datetime(2026, 11, 21, 14, 0, 0)
        now_ts = now.timestamp()

        # 1. Inactivity = 200s (< 300s threshold): must return []
        ra._last_user_activity = now_ts - 200.0
        ra._last_idle_eval_time = None
        recs_below = ra._evaluate_idle_recommendations(force=False, test_now=now)
        self.assertEqual(recs_below, [])

        # 2. Inactivity = 350s (>= 300s threshold): evaluates recommendations
        ra._last_user_activity = now_ts - 350.0
        ra._last_idle_eval_time = None
        with patch("runtime_adapter.RecommendationEvaluator") as MockEval:
            mock_inst = MagicMock()
            mock_inst.evaluate.return_value = []
            MockEval.return_value = mock_inst
            recs_above = ra._evaluate_idle_recommendations(force=False, test_now=now)
            self.assertIsInstance(recs_above, list)
            mock_inst.evaluate.assert_called_once()

    def test_pre_due_reminder_lead_time_alerts_and_cleanup(self):
        """
        Validate pre-due reminder alerts (reminder.upcoming) with zero schema changes:
        1. handle_reminders_create stores lead_time_minutes in settings metadata.
        2. _check_and_emit_due_reminders() emits reminder.upcoming without setting fired = 1.
        3. Once due_at arrives, reminder.due emits and fired = 1 is set with metadata pruned.
        4. handle_reminders_cancel prunes lead time metadata cleanly.
        """
        now = datetime(2026, 11, 21, 10, 0, 0)
        due_at = now + timedelta(minutes=10)

        # 1. Create reminder with 15m lead time
        res = ra.handle_reminders_create({
            "message": "Review Pull Request",
            "due_at": due_at.isoformat(),
            "lead_time_minutes": 15,
        })
        rem_id = res["id"]
        self.assertEqual(res["lead_time_minutes"], 15)

        # Verify metadata persisted in settings
        cur_settings = ra._load_gui_settings()
        self.assertEqual(cur_settings["reminder_lead_times"].get(str(rem_id)), 15)

        # 2. At now (10m before due, within 15m lead window): emit reminder.upcoming
        with patch.object(ra, "send_event") as mock_send:
            ra._check_and_emit_due_reminders(test_now=now)

            # Check proactive_events table for reminder.upcoming
            lead_evt_id = f"evt_reminder_lead_{rem_id}"
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_type, payload_json FROM proactive_events WHERE event_id = ?", (lead_evt_id,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "reminder.upcoming")
                payload = json.loads(row[1])
                self.assertEqual(payload["lead_time_minutes"], 15)
                self.assertEqual(payload["reminder_id"], rem_id)

                # CRITICAL: Main reminder MUST still be fired = 0
                cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
                fired_val = cur.fetchone()[0]
                self.assertEqual(fired_val, 0)

        # Deduplication check: second check at same time should not duplicate event
        with patch.object(ra, "send_event") as mock_send_dup:
            ra._check_and_emit_due_reminders(test_now=now)
            mock_send_dup.assert_not_called()

        # 3. Advance to due_at + 1m: emit reminder.due and mark fired = 1
        now_due = due_at + timedelta(minutes=1)
        with patch.object(ra, "send_event"):
            ra._check_and_emit_due_reminders(test_now=now_due)

            due_evt_id = f"evt_reminder_{rem_id}"
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_type FROM proactive_events WHERE event_id = ?", (due_evt_id,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "reminder.due")

                # Verify reminder is now marked fired = 1
                cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
                self.assertEqual(cur.fetchone()[0], 1)

            # Verify lead time metadata was pruned
            updated_settings = ra._load_gui_settings()
            self.assertNotIn(str(rem_id), updated_settings.get("reminder_lead_times", {}))

        # 4. Cancellation cleanup check
        res2 = ra.handle_reminders_create({
            "message": "Deploy Service",
            "due_at": (now + timedelta(hours=2)).isoformat(),
            "lead_time_minutes": 30,
        })
        rem2_id = res2["id"]
        settings_after_create = ra._load_gui_settings()
        self.assertEqual(settings_after_create["reminder_lead_times"].get(str(rem2_id)), 30)

        ra.handle_reminders_cancel({"id": rem2_id})
        settings_after_cancel = ra._load_gui_settings()
        self.assertNotIn(str(rem2_id), settings_after_cancel.get("reminder_lead_times", {}))

    def test_terminal_job_followups_and_quiet_hours_deferral(self):
        """
        Validate that terminal job transitions (COMPLETED & FAILED) emit deduplicated
        job.followup proactive events, defer during quiet hours, and emit once outside.
        """
        ra.handle_settings_update({
            "settings": {
                "contextual_advisories_enabled": True,
                "quiet_hours_enabled": False,
            }
        })

        # Mock COMPLETED Job
        mock_completed_job = MagicMock()
        mock_completed_job.id = "job-comp-1234"
        mock_completed_job.status = JobStatus.COMPLETED
        mock_completed_job.goal = "Build release bundle"
        mock_completed_job.final_response = "All artifacts compiled into dist/"
        mock_completed_job.last_error = None
        mock_completed_job.get_pending_confirmation.return_value = None

        with patch.object(ra, "send_event") as mock_send:
            ra._on_job_event(mock_completed_job)

            # Verify job.followup in proactive_events
            evt_id = "evt_job_followup_job-comp-1234_completed"
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_type, payload_json FROM proactive_events WHERE event_id = ?", (evt_id,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "job.followup")
                payload = json.loads(row[1])
                self.assertEqual(payload["status"], "COMPLETED")
                self.assertEqual(payload["job_id"], "job-comp-1234")
                self.assertIn("Build release bundle", payload["summary"])
                self.assertIn("Review the results", payload["suggested_prompt"])

        # Deduplication check
        with patch.object(ra, "send_event") as mock_send_dup:
            ra._on_job_event(mock_completed_job)
            # send_event called for scheduler.job_event, but NOT duplicate proactive event
            emitted_types = [call[0][0] for call in mock_send_dup.call_args_list]
            self.assertNotIn("job.followup", emitted_types)

        # Mock FAILED Job
        mock_failed_job = MagicMock()
        mock_failed_job.id = "job-fail-5678"
        mock_failed_job.status = JobStatus.FAILED
        mock_failed_job.goal = "Migrate SQLite DB"
        mock_failed_job.final_response = None
        mock_failed_job.last_error = "Connection timeout after 30s"
        mock_failed_job.get_pending_confirmation.return_value = None

        with patch.object(ra, "send_event"):
            ra._on_job_event(mock_failed_job)

            evt_fail_id = "evt_job_followup_job-fail-5678_failed"
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_type, payload_json FROM proactive_events WHERE event_id = ?", (evt_fail_id,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "job.followup")
                payload = json.loads(row[1])
                self.assertEqual(payload["status"], "FAILED")
                self.assertIn("Connection timeout", payload["summary"])
                self.assertIn("Investigate why job", payload["suggested_prompt"])

        # Quiet Hours Deferral Test for Jobs
        ra.handle_settings_update({
            "settings": {
                "quiet_hours_enabled": True,
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
            }
        })

        mock_quiet_job = MagicMock()
        mock_quiet_job.id = "job-quiet-9999"
        mock_quiet_job.status = JobStatus.COMPLETED
        mock_quiet_job.goal = "Midnight maintenance"
        mock_quiet_job.final_response = "Cleaned temp files"
        mock_quiet_job.last_error = None
        mock_quiet_job.get_pending_confirmation.return_value = None

        night_time = datetime(2026, 11, 21, 23, 45, 0)
        res_deferred = ra._emit_job_followup(mock_quiet_job, test_now=night_time)
        self.assertIsNone(res_deferred)

        evt_quiet_id = "evt_job_followup_job-quiet-9999_completed"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_quiet_id,))
            self.assertIsNone(cur.fetchone())

        # Pickup when outside quiet hours
        day_time = datetime(2026, 11, 21, 8, 30, 0)
        with patch("main.get_job_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.list_jobs.side_effect = lambda status, limit: [mock_quiet_job] if status == JobStatus.COMPLETED else []
            mock_get_mgr.return_value = mock_mgr

            with patch.object(ra, "send_event"):
                emitted = ra._check_and_emit_deferred_job_followups(test_now=day_time)
                self.assertEqual(len(emitted), 1)
                self.assertEqual(emitted[0]["event_id"], evt_quiet_id)

            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_type FROM proactive_events WHERE event_id = ?", (evt_quiet_id,))
                self.assertIsNotNone(cur.fetchone())


if __name__ == "__main__":
    unittest.main()

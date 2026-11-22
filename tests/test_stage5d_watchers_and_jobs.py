"""
tests/test_stage5d_watchers_and_jobs.py - Stage 5D Multi-Step Goal Loop, Watchers & Standing Jobs Test Suite.

Covers:
1. Multi-Step Goal Loop:
   - Sequential execution of tools (e.g. create_directory -> write_file -> observation -> conclusion).
   - Catastrophic command block during autonomous multi-step turn.
   - User confirmation rejection handling during multi-step turn.
   - Structured tool_steps array capturing step index, arguments, status, and outputs.
2. Git/Workspace Watchers:
   - scan_workspace_watchers returns structured metadata (branch, commit epoch/iso, uncommitted count) for active repositories.
   - Safe execution on missing, non-git, or uninitialized directories.
3. Friction-Loop Detection:
   - record_workspace_failure tracks failures over time.
   - Emits watcher_alert proactive event on 3+ failures within 10 minutes (600s).
   - Pruning of failures older than 10 minutes.
4. Render /health Watchdog:
   - Probes /health on scheduler ticks with 15-minute (900s) throttling.
   - Emits watcher_alert on connection failure or non-200 status code.
5. Standing Agent Jobs:
   - ensure_default_standing_jobs idempotently seeds:
     * Daily Morning Briefing & Priority Digest
     * Workspace & Git Hygiene Audit
     * Overdue Reminder & Blocker Escalation
   - Running repeatedly produces zero duplicates.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
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
import tools.permissions as tool_perm


class BaseStage5DIsolatedTest(unittest.TestCase):
    """Base test class providing temporary isolated environment for Stage 5D testing."""

    def setUp(self):
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage5d_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        self._reset_engine_state()
        mem.initialize_memory()
        conn = mem.get_connection()
        rem_mod._init_db(conn)
        from brain.jobs.store import JobStore
        job_db = os.path.join(self.temp_user_dir, "memory.db")
        store = JobStore(job_db)
        main.job_store = store
        main.job_manager = None
        runtime_adapter._ensure_stage2c_tables()
        main.ensure_initialized()

        # Reset in-memory watchers state
        runtime_adapter._workspace_failure_history = []
        runtime_adapter._last_health_check_ts = 0.0

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
        main.job_manager = None
        main.job_store = None
        main.job_runtime = None
        runtime_adapter._workspace_failure_history = []


class TestStage5DWatchersAndJobs(BaseStage5DIsolatedTest):
    """Verifies workspace watchers, friction-loop detection, watchdog, and standing jobs."""

    def test_01_workspace_watchers_scan(self):
        """scan_workspace_watchers returns structured git metadata for repositories."""
        watchers = runtime_adapter.scan_workspace_watchers()
        self.assertIsInstance(watchers, dict)

        # Should detect at least Orange AI Tauri and Orange API (valid git repos in D:\Orange AI)
        self.assertIn("Orange AI Tauri", watchers)
        self.assertIn("Orange API", watchers)

        tauri_info = watchers["Orange AI Tauri"]
        self.assertEqual(tauri_info["name"], "Orange AI Tauri")
        self.assertTrue(tauri_info["branch"])
        self.assertGreater(tauri_info["latest_commit_epoch"], 0)
        self.assertTrue(tauri_info["latest_commit_iso"])
        self.assertIsInstance(tauri_info["uncommitted_changes_count"], int)

    def test_02_friction_loop_detection(self):
        """record_workspace_failure alerts only after 3+ failures within 10 minutes."""
        ws_name = "TestFrictionRepo"

        # Failure 1: no alert
        runtime_adapter.record_workspace_failure(ws_name, "Compilation error 1")
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM proactive_events WHERE event_type = 'watcher_alert'")
            count1 = cur.fetchone()[0]
        self.assertEqual(count1, 0)

        # Failure 2: no alert
        runtime_adapter.record_workspace_failure(ws_name, "Compilation error 2")
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM proactive_events WHERE event_type = 'watcher_alert'")
            count2 = cur.fetchone()[0]
        self.assertEqual(count2, 0)

        # Failure 3: triggers watcher_alert
        runtime_adapter.record_workspace_failure(ws_name, "Compilation error 3")
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT payload_json FROM proactive_events WHERE event_type = 'watcher_alert'")
            rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(payload["alert_type"], "friction_loop")
        self.assertEqual(payload["workspace"], ws_name)
        self.assertEqual(payload["failure_count"], 3)
        self.assertIn("3 failures within 10 minutes", payload["message"])

    def test_03_friction_loop_time_pruning(self):
        """Failures older than 10 minutes (600s) are pruned and do not trigger alert."""
        ws_name = "PrunedRepo"
        old_time = time.time() - 700.0  # 11+ minutes ago

        # Add 2 old failures
        runtime_adapter._workspace_failure_history.append({
            "workspace": ws_name,
            "timestamp": old_time,
            "error": "Old failure 1",
        })
        runtime_adapter._workspace_failure_history.append({
            "workspace": ws_name,
            "timestamp": old_time,
            "error": "Old failure 2",
        })

        # Add 1 current failure -> total recent = 1 (the 2 old ones get pruned)
        runtime_adapter.record_workspace_failure(ws_name, "New failure")
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM proactive_events WHERE event_type = 'watcher_alert'")
            count = cur.fetchone()[0]
        self.assertEqual(count, 0, "Pruned old failures should not trigger friction alert")
        self.assertEqual(len(runtime_adapter._workspace_failure_history), 1)

    @patch("requests.get")
    def test_04_render_health_watchdog_and_throttling(self, mock_get):
        """Render /health watchdog emits alert on failure and is throttled to 15m (900s)."""
        mock_get.side_effect = Exception("Connection refused by endpoint")

        runtime_adapter._last_health_check_ts = 0.0

        # Tick 1: Executes health probe and records watcher_alert
        tick1 = runtime_adapter.run_scheduler_tick(now=datetime(2026, 11, 22, 10, 0, 0))
        self.assertTrue(tick1["health_probe_executed"])

        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT payload_json FROM proactive_events WHERE event_type = 'watcher_alert'")
            rows = cur.fetchall()
        self.assertGreater(len(rows), 0)
        payload = json.loads(rows[0][0])
        self.assertEqual(payload["alert_type"], "render_health")
        self.assertEqual(payload["status"], "error")

        # Tick 2 (1 minute later, 60s < 900s): health probe is throttled
        tick2 = runtime_adapter.run_scheduler_tick(now=datetime(2026, 11, 22, 10, 1, 0))
        self.assertFalse(tick2["health_probe_executed"])

    def test_05_idempotent_standing_jobs(self):
        """ensure_default_standing_jobs seeds 3 default jobs idempotently."""
        mgr = main.get_job_manager()
        self.assertIsNotNone(mgr)

        # Clear any existing jobs in test DB
        for j in mgr.list_jobs(limit=100):
            try:
                mgr.cancel(j.id)
            except Exception:
                pass

        # First run: seeds 3 jobs
        seeded_first = runtime_adapter.ensure_default_standing_jobs()
        self.assertEqual(len(seeded_first), 3)

        jobs_after_first = mgr.list_jobs(limit=100)
        goals = {j.goal for j in jobs_after_first}
        self.assertIn("Daily Morning Briefing & Priority Digest", goals)
        self.assertIn("Workspace & Git Hygiene Audit", goals)
        self.assertIn("Overdue Reminder & Blocker Escalation", goals)

        # Second run: seeds 0 duplicate jobs
        seeded_second = runtime_adapter.ensure_default_standing_jobs()
        self.assertEqual(len(seeded_second), 0)

        jobs_after_second = mgr.list_jobs(limit=100)
        self.assertEqual(len(jobs_after_second), 3)


class TestStage5DMultiStepGoalLoop(BaseStage5DIsolatedTest):
    """Verifies bounded multi-step autonomous execution and safety guardrails."""

    def test_01_catastrophic_tool_blocked_immediately(self):
        """Autonomous loop halts immediately on Step 1 if tool is catastrophic."""
        turn_input = "[TOOL: run_powershell(command=\"format C: /fs:ntfs\")]"

        res = runtime_adapter.process_user_turn(turn_input)
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(len(res["tool_steps"]), 1)
        self.assertEqual(res["tool_steps"][0]["status"], "BLOCKED")
        self.assertIn("Safety Guardrail", res["reply"])

    def test_02_confirmation_declined_halts_loop(self):
        """In supervised mode, declining confirmation outside workspace halts loop safely."""
        target_path = r"C:\random_non_workspace_location\test.txt"
        turn_input = f"[TOOL: write_file(path=\"{target_path}\", content=\"hello\")]"

        # Simulate user typing 'n' (decline)
        res = runtime_adapter.process_user_turn(turn_input, prompt_fn=lambda _: "n")
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(len(res["tool_steps"]), 1)
        self.assertEqual(res["tool_steps"][0]["status"], "CANCELLED")
        self.assertIn("Operation cancelled with zero changes made", res["reply"])

    def test_03_multistep_sequential_chaining_and_completion(self):
        """Chains multiple steps (create directory -> write file) and concludes upon goal verification."""
        test_dir = os.path.join(self.temp_user_dir, "autonomy_workspace")
        test_file = os.path.join(test_dir, "notes.txt")

        # Step 1: Initial user turn requests directory creation
        turn_input = f"[TOOL: create_directory(path=\"{test_dir}\")]"

        responses = [
            {"reply": f"[TOOL: write_file(path=\"{test_file}\", content=\"Step 2 complete\")]"},
            {"reply": "Goal verified: directory created and notes.txt written successfully."},
        ]

        with patch.object(main.api_client, "assist", side_effect=responses):
            res = runtime_adapter.process_user_turn(turn_input)
            self.assertIn("Goal verified", res["reply"])
            self.assertEqual(len(res["tool_steps"]), 2)

            # Verify Step 1 record
            self.assertEqual(res["tool_steps"][0]["step"], 1)
            self.assertEqual(res["tool_steps"][0]["tool"], "create_directory")
            self.assertEqual(res["tool_steps"][0]["status"], "SUCCESS")

            # Verify Step 2 record
            self.assertEqual(res["tool_steps"][1]["step"], 2)
            self.assertEqual(res["tool_steps"][1]["tool"], "write_file")
            self.assertEqual(res["tool_steps"][1]["status"], "SUCCESS")

            # Verify filesystem side effects actually occurred
            self.assertTrue(os.path.isdir(test_dir))
            self.assertTrue(os.path.isfile(test_file))
            with open(test_file, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "Step 2 complete")


if __name__ == "__main__":
    unittest.main()

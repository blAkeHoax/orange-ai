"""
test_stage2_everyday_reliability.py - Stage 2 Everyday Reliability End-to-End Integration Suite.

Validates all 5 Stage 2 everyday reliability pillars using the real runtime/engine stack:
1. Memory Lifecycle & Process Restart Persistence
   - Structured memory & conversation turn persistence
   - Context budgeting and retrieval relevance (ContextBudgetManager)
   - Update, retraction, and forget operations
   - Process restart persistence across simulated restarts
2. File Operations & Permission Enforcement
   - SAFE tools (list_files, read_file, find_file) execute immediately without prompts
   - edit_file (CONFIRMATION_REQUIRED) execution upon approval
   - edit_file abort and content preservation upon denial or timeout
   - HIGH_RISK policy check unconditional denial (even for admin)
3. Multi-Step Agent Execution & Job Concurrency
   - Multi-step goal execution via AgentEngine + JobManager with deterministic stubbed OrangeAPIClient
   - Step progression, tool execution logs, and final COMPLETED transition
   - JobManager concurrency invariant: only one job RUNNING at any time; second job remains PENDING
4. Error Handling & Crash / Restart Recovery (recover_interrupted())
   - Transient failure handling within MAX_RETRIES = 2
   - Crash mid-job with certainty established -> safe transition to PAUSED
   - Crash mid-job with uncertainty (unfinalized step) -> RETRYING or FAILED
   - Crash post-terminal step -> COMPLETED
   - Repeated crash boundary detection -> FAILED (DEF-06)
5. Reminders & Restart Survival
   - Reminder scheduling and due check evaluation (_check_and_emit_due_reminders)
   - Persistence in proactive_events and single emission
   - Acknowledgment via events.ack and restart deduplication
"""

import io
import os
import sys
import json
import uuid
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
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

# Import runtime and desktop modules
import runtime_adapter
import main
import brain.memory as mem
import brain.reminders as reminders
import brain.mood as mood
import brain.planner as planner
from brain.database import resolve_database_path
from brain.context_budget import (
    ContextBudgetManager,
    budget_chat_memory,
    budget_agent_memory,
)
from brain.jobs.models import Job, JobStep, JobStatus
from brain.jobs.store import JobStore
from brain.jobs.runtime import JobRuntime
from brain.jobs.manager import JobManager
from brain.agent import AgentEngine
from brain.agent_models import (
    AgentState,
    AgentStatus,
    AgentAction,
    ActionType,
    ToolResult,
)
from tools.registry import Tool, ToolRegistry, create_default_registry, registry
from tools.permissions import (
    RiskLevel,
    PermissionStatus,
    check_permission,
    execute_with_permission,
)
from tools.files import list_files, read_file, find_file, edit_file


class BaseStage2IsolatedTest(unittest.TestCase):
    """Base test class providing strict data isolation and clean state resets."""

    def setUp(self):
        # 1. Create a dedicated temporary directory for user data
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage2_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        # 2. Dedicated temporary sandbox directory for file tool operations
        self.temp_sandbox_dir = tempfile.mkdtemp(prefix="orange_test_sandbox_")

        # 3. Clean any existing database connections and global state
        self._reset_engine_state()

        # 4. Initialize database tables in isolated environment
        mem.initialize_memory()
        runtime_adapter._ensure_stage2c_tables()
        main.ensure_initialized()

    def tearDown(self):
        # 1. Close all connections
        self._reset_engine_state()

        # 2. Restore environment variable
        if self.orig_user_data_dir is not None:
            os.environ["ORANGE_AI_USER_DATA_DIR"] = self.orig_user_data_dir
        elif "ORANGE_AI_USER_DATA_DIR" in os.environ:
            del os.environ["ORANGE_AI_USER_DATA_DIR"]

        # 3. Clean up temporary directories
        shutil.rmtree(self.temp_user_dir, ignore_errors=True)
        shutil.rmtree(self.temp_sandbox_dir, ignore_errors=True)

    def _reset_engine_state(self):
        """Close DB handles and clear shared global singletons."""
        try:
            mem.close()
        except Exception:
            pass
        try:
            reminders.close()
        except Exception:
            pass
        try:
            mood.close()
        except Exception:
            pass
        try:
            planner.close()
        except Exception:
            pass

        main.history = None
        main.job_store = None
        main.job_runtime = None
        main.job_manager = None
        main.agent_engine = None
        main.api_client = None

        with runtime_adapter._confirmations_lock:
            runtime_adapter._pending_confirmations.clear()


# =============================================================================
# Pillar 1: Memory Lifecycle & Process Restart Persistence
# =============================================================================

class TestStage2MemoryLifecycle(BaseStage2IsolatedTest):
    """Validates structured memory storage, retrieval, budgeting, mutation, and restart persistence."""

    def test_01_store_structured_memories_and_turns(self):
        """Store structured memories and conversation turns; verify retrieval via runtime RPC."""
        # 1. Store structured memories across categories
        mem.remember_structured("project", "Zephyr", "Autonomous drone navigation software", confidence=1.0)
        mem.remember_structured("preference", "editor", "VS Code", confidence=1.0)
        mem.remember_structured("preference", "theme", "dark", confidence=0.9)
        mem.remember_structured("identity", "name", "Sayan", confidence=1.0)

        # 2. Store conversation turns
        mem.save_turn("user", "Hello! I am setting up the Zephyr drone project in VS Code.")
        mem.save_turn("assistant", "Welcome Sayan! I've recorded your project Zephyr and preferred editor VS Code.")

        # 3. Verify via runtime RPC handlers
        structured = runtime_adapter.handle_memory_structured({})
        self.assertIsInstance(structured, list)
        self.assertGreaterEqual(len(structured), 4)

        cat_keys = {(m["category"], m["key"]): m["value"] for m in structured}
        self.assertIn(("project", "zephyr"), cat_keys)
        self.assertEqual(cat_keys[("project", "zephyr")], "Autonomous drone navigation software")
        self.assertIn(("preference", "editor"), cat_keys)
        self.assertEqual(cat_keys[("preference", "editor")], "VS Code")
        self.assertIn(("identity", "name"), cat_keys)
        self.assertEqual(cat_keys[("identity", "name")], "Sayan")

        # 4. Verify chat history via runtime RPC
        history = runtime_adapter.handle_chat_history({"limit": 10})
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertIn("Zephyr", history[0]["content"])
        self.assertEqual(history[1]["role"], "assistant")

    def test_02_context_budgeting_surfaces_relevant_memories(self):
        """Context budgeting surfaces relevant project and preference memories within bounds."""
        mem.remember_structured("project", "Zephyr", "Autonomous drone navigation software", confidence=1.0)
        mem.remember_structured("preference", "editor", "VS Code", confidence=1.0)
        mem.remember_structured("preference", "language", "Python", confidence=0.9)

        # Budget for conversational query related to Zephyr
        budget_res = budget_chat_memory(query="What drone software is Zephyr?", max_chars=1500)
        profile_text = budget_res.formatted_profile

        self.assertIn("[PROJECT]", profile_text)
        self.assertIn("zephyr: Autonomous drone navigation software", profile_text)

        # Budget for agent goal
        agent_budget = budget_agent_memory(goal="Configure VS Code editor settings for Zephyr", max_chars=1200)
        self.assertIsNotNone(agent_budget)
        combined_text = agent_budget.formatted_profile + " " + (agent_budget.formatted_legacy or "")
        self.assertTrue("Zephyr" in combined_text or "VS Code" in combined_text)

    def test_03_memory_update_and_retraction_lifecycle(self):
        """Update existing memory and delete/retract another; verify active memory set changes."""
        mem.remember_structured("preference", "editor", "VS Code", confidence=1.0)
        mem.remember_structured("preference", "theme", "light", confidence=1.0)

        # Update editor preference to Neovim
        mem.update_memory("preference", "editor", "Neovim")

        structured = runtime_adapter.handle_memory_structured({})
        cat_keys = {(m["category"], m["key"]): m["value"] for m in structured}
        self.assertEqual(cat_keys.get(("preference", "editor")), "Neovim")

        # Retract theme preference via runtime RPC
        retract_res = runtime_adapter.handle_memory_retract({"category": "preference", "key": "theme"})
        self.assertEqual(retract_res.get("status"), "removed")
        self.assertEqual(retract_res.get("deleted_structured"), 1)

        structured_after = runtime_adapter.handle_memory_structured({})
        keys_after = {(m["category"], m["key"]) for m in structured_after}
        self.assertNotIn(("preference", "theme"), keys_after)
        self.assertIn(("preference", "editor"), keys_after)

    def test_04_process_restart_persistence(self):
        """Simulate process restart: created/updated memories persist and deleted memories remain absent."""
        # 1. Seed initial data and mutate
        mem.remember_structured("project", "Zephyr", "Autonomous drone flight software", confidence=1.0)
        mem.remember_structured("preference", "editor", "VS Code", confidence=1.0)
        mem.remember_structured("preference", "obsolete_key", "old_value", confidence=1.0)
        mem.save_turn("user", "Save this session turn.")
        mem.update_memory("preference", "editor", "Neovim")
        mem.delete_memory("preference", "obsolete_key")

        # 2. Simulate complete process crash / shutdown
        self._reset_engine_state()

        # 3. Simulate process startup against the EXACT same isolated user data directory
        mem.initialize_memory()
        runtime_adapter._ensure_stage2c_tables()
        main.ensure_initialized()

        # 4. Verify persistent state after restart
        structured = runtime_adapter.handle_memory_structured({})
        cat_keys = {(m["category"], m["key"]): m["value"] for m in structured}

        self.assertIn(("project", "zephyr"), cat_keys)
        self.assertEqual(cat_keys[("project", "zephyr")], "Autonomous drone flight software")
        self.assertIn(("preference", "editor"), cat_keys)
        self.assertEqual(cat_keys[("preference", "editor")], "Neovim")
        self.assertNotIn(("preference", "obsolete_key"), cat_keys)

        # 5. Verify conversation history turns survived restart
        history = runtime_adapter.handle_chat_history({"limit": 10})
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "Save this session turn.")


# =============================================================================
# Pillar 2: File Operations & Permission Enforcement
# =============================================================================

class TestStage2FileOperationsAndPermissions(BaseStage2IsolatedTest):
    """Validates SAFE tool execution, CONFIRMATION_REQUIRED approval/rejection/timeout, and HIGH_RISK policy."""

    def test_05_safe_file_tools_execute_without_prompting(self):
        """SAFE file tools (list_files, read_file, find_file) execute immediately without confirmation prompts."""
        sandbox = Path(self.temp_sandbox_dir)
        test_file = sandbox / "sample.txt"
        test_file.write_text("Hello from Orange AI Stage 2 test.\nSecond line.\n", encoding="utf-8")

        reg = create_default_registry()
        list_tool = reg.get("list_files")
        read_tool = reg.get("read_file")
        find_tool = reg.get("find_file")

        self.assertEqual(list_tool.risk_level, RiskLevel.SAFE)
        self.assertEqual(read_tool.risk_level, RiskLevel.SAFE)
        self.assertEqual(find_tool.risk_level, RiskLevel.SAFE)

        prompt_mock = MagicMock(return_value="no")

        # 1. list_files
        list_res = execute_with_permission(list_tool, args=(str(sandbox),), kwargs={}, prompt_fn=prompt_mock)
        prompt_mock.assert_not_called()
        self.assertIn("sample.txt", str(list_res))

        # 2. read_file
        read_res = execute_with_permission(read_tool, args=(str(test_file),), kwargs={}, prompt_fn=prompt_mock)
        prompt_mock.assert_not_called()
        self.assertIn("Hello from Orange AI Stage 2 test.", str(read_res))

        # 3. find_file
        find_res = execute_with_permission(find_tool, args=("sample.txt", str(sandbox)), kwargs={}, prompt_fn=prompt_mock)
        prompt_mock.assert_not_called()
        self.assertIn("sample.txt", str(find_res))

    def test_06_confirmation_required_edit_file_approved(self):
        """edit_file (CONFIRMATION_REQUIRED) prompts user and applies modification when approved."""
        sandbox = Path(self.temp_sandbox_dir)
        target = sandbox / "config.yaml"
        target.write_text("version: 1.0.0\nenvironment: development\n", encoding="utf-8")
        backup_dir = sandbox / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        reg = create_default_registry()
        edit_tool = reg.get("edit_file")
        self.assertEqual(edit_tool.risk_level, RiskLevel.CONFIRMATION_REQUIRED)

        # Mock affirmative confirmation
        prompt_mock = MagicMock(return_value="yes")

        res = execute_with_permission(
            edit_tool,
            args=(str(target), "environment: development", "environment: production"),
            kwargs={"backup_dir": str(backup_dir)},
            prompt_fn=prompt_mock,
        )

        prompt_mock.assert_called_once()
        self.assertIn("Successfully replaced", str(res))
        self.assertIn("environment: production", target.read_text(encoding="utf-8"))

    def test_07_confirmation_required_edit_file_rejected(self):
        """edit_file (CONFIRMATION_REQUIRED) aborts and leaves file untouched when user rejects."""
        sandbox = Path(self.temp_sandbox_dir)
        target = sandbox / "sensitive.env"
        initial_content = "API_KEY=prod-secret-999\nDEBUG=false\n"
        target.write_text(initial_content, encoding="utf-8")
        backup_dir = sandbox / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        reg = create_default_registry()
        edit_tool = reg.get("edit_file")

        # Mock user rejection
        prompt_mock = MagicMock(return_value="no")

        res = execute_with_permission(
            edit_tool,
            args=(str(target), "DEBUG=false", "DEBUG=true"),
            kwargs={"backup_dir": str(backup_dir)},
            prompt_fn=prompt_mock,
        )

        prompt_mock.assert_called_once()
        self.assertIn("Action cancelled: user declined confirmation", str(res))
        # Verify content on disk remains completely unchanged
        self.assertEqual(target.read_text(encoding="utf-8"), initial_content)

    def test_08_confirmation_bridge_timeout_aborts_safely(self):
        """Confirmation bridge defaults to denial upon timeout and preserves filesystem state."""
        sandbox = Path(self.temp_sandbox_dir)
        target = sandbox / "data.json"
        initial_data = '{"status": "intact"}'
        target.write_text(initial_data, encoding="utf-8")

        reg = create_default_registry()
        edit_tool = reg.get("edit_file")

        # Test _confirmation_prompt_fn timeout behavior by patching evt.wait to return False (timed out)
        with patch.object(threading.Event, "wait", return_value=False):
            with patch("runtime_adapter.send_event") as mock_send_event:
                res = execute_with_permission(
                    edit_tool,
                    args=(str(target), '"intact"', '"corrupted"'),
                    kwargs={},
                    prompt_fn=runtime_adapter._confirmation_prompt_fn,
                )

        self.assertIn("Action cancelled: user declined confirmation", str(res))
        self.assertEqual(target.read_text(encoding="utf-8"), initial_data)

    def test_09_high_risk_policy_unconditional_denial(self):
        """Any tool classified as HIGH_RISK is unconditionally denied, even for administrator."""
        dummy_func = MagicMock()
        high_risk_tool = Tool(
            name="format_system_drive",
            description="Destructive system disk formatting",
            risk_level=RiskLevel.HIGH_RISK,
            func=dummy_func,
            category="system",
        )

        # Standard permission evaluation
        perm_standard = check_permission(high_risk_tool, is_admin=False)
        self.assertEqual(perm_standard.status, PermissionStatus.DENIED)
        self.assertIn("classified as HIGH_RISK", perm_standard.reason)

        # Administrator permission evaluation (must NOT override)
        perm_admin = check_permission(high_risk_tool, is_admin=True)
        self.assertEqual(perm_admin.status, PermissionStatus.DENIED)
        self.assertIn("classified as HIGH_RISK", perm_admin.reason)

        # Execute with permission (is_admin=True)
        res = execute_with_permission(high_risk_tool, args=(), kwargs={}, is_admin=True)
        self.assertIn("Action blocked:", res)
        self.assertIn("classified as HIGH_RISK", res)
        dummy_func.assert_not_called()


# =============================================================================
# Pillar 3: Multi-Step Agent Execution & Job Concurrency
# =============================================================================

class TestStage2AgentJobsAndConcurrency(BaseStage2IsolatedTest):
    """Validates multi-step agent execution, step logging, and JobManager concurrency invariant."""

    def test_10_multistep_agent_job_progression(self):
        """Execute a multi-step job with tool call and completion; verify step logging and final status."""
        sandbox = Path(self.temp_sandbox_dir)
        (sandbox / "file_a.txt").write_text("File A", encoding="utf-8")
        (sandbox / "file_b.txt").write_text("File B", encoding="utf-8")

        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)

        # Deterministic mock LLM: step 1 calls list_files, step 2 completes task
        class MockStepAPIClient:
            def __init__(self):
                self.turn = 0

            def assist(self, *args, **kwargs):
                self.turn += 1
                if self.turn == 1:
                    decision = {
                        "action": {
                            "type": "CALL_TOOL",
                            "tool_name": "list_files",
                            "arguments": {"path": str(sandbox)},
                            "reasoning_summary": "Listing directory to inspect workspace",
                        }
                    }
                    return {"reply": json.dumps(decision), "model": "nvidia/nemotron", "success": True}
                else:
                    decision = {
                        "action": {
                            "type": "FINISH",
                            "response": "Workspace inspection complete. Found 2 files.",
                            "reasoning_summary": "All required files verified",
                        }
                    }
                    return {"reply": json.dumps(decision), "model": "nvidia/nemotron", "success": True}

        mock_api = MockStepAPIClient()
        engine = AgentEngine(api_client=mock_api)
        runtime = JobRuntime(store=store, engine=engine)
        mgr = JobManager(store=store, runtime=runtime)

        # Create and execute job
        job = mgr.create("Inspect workspace files")
        self.assertEqual(job.status, JobStatus.PENDING)

        completed_job = mgr.start(job.id)
        self.assertEqual(completed_job.status, JobStatus.COMPLETED)
        self.assertEqual(completed_job.final_response, "Workspace inspection complete. Found 2 files.")

        # Verify step audit log in SQLite
        steps = mgr.get_history(job.id)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].action_type, "CALL_TOOL")
        self.assertEqual(steps[0].tool_name, "list_files")
        self.assertTrue(steps[0].success)
        self.assertEqual(steps[1].action_type, "FINISH")
        self.assertTrue(steps[1].success)

    def test_11_job_manager_concurrency_invariant(self):
        """Starting a job while another job is RUNNING places the second job in PENDING."""
        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)
        mgr = JobManager(store=store)

        # Create job 1 and set its status to RUNNING (simulating active in-flight worker)
        job1 = store.create_job(goal="Active long-running job", status=JobStatus.RUNNING)

        # Create job 2 in PENDING status
        job2 = mgr.create("Secondary queued job")
        self.assertEqual(job2.status, JobStatus.PENDING)

        # Attempt to start job 2 while job 1 is running
        started_job2 = mgr.start(job2.id)

        # Concurrency invariant: Job 2 must remain PENDING
        self.assertEqual(started_job2.status, JobStatus.PENDING)
        stored_job2 = mgr.get_job(job2.id)
        self.assertEqual(stored_job2.status, JobStatus.PENDING)


# =============================================================================
# Pillar 4: Error Handling & Crash / Restart Recovery
# =============================================================================

class TestStage2CrashRecoveryAndErrorHandling(BaseStage2IsolatedTest):
    """Validates transient retry bounding and recover_interrupted() crash recovery policies."""

    def test_12_transient_failure_retry_ceiling(self):
        """Repeated LLM or parsing errors honor MAX_RETRIES = 2 and transition cleanly without infinite loop."""
        class FailingAPIClient:
            def assist(self, *args, **kwargs):
                return {"reply": "This is invalid non-JSON output that causes parsing errors.", "model": "test", "success": True}

        failing_api = FailingAPIClient()
        engine = AgentEngine(api_client=failing_api, max_retries=2)

        # Start agent run
        state = engine.start_run("A task destined to encounter repeated model formatting errors")

        self.assertEqual(state.status, AgentStatus.MAX_RETRIES_REACHED)
        self.assertIn("maximum retries (2) reached", state.final_response)

    def test_13_crash_recovery_certainty_established_paused(self):
        """Mid-job crash with matching completed steps and checkpoint safely recovers as PAUSED."""
        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)

        # 1. Simulate an interrupted job left in RUNNING
        job = store.create_job(goal="Interrupted mid-step job", status=JobStatus.RUNNING)
        step1 = JobStep(
            job_id=job.id,
            attempt=1,
            step_index=1,
            action_type="CALL_TOOL",
            tool_name="list_files",
            success=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        store.record_step(step1)

        # Checkpoint matching observation count (certainty established)
        state = AgentState(
            run_id="run_crashed_1",
            goal=job.goal,
            original_request=job.goal,
            status=AgentStatus.RUNNING,
            step_count=1,
            observations=[{"step": 1, "action": {"type": "CALL_TOOL"}, "result": {"success": True}}],
        )
        store.save_checkpoint(job.id, state)

        # 2. Reinitialize manager (simulating startup) and recover
        mgr = JobManager(store=store)
        recovered = mgr.recover_interrupted()

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].id, job.id)
        self.assertEqual(recovered[0].status, JobStatus.PAUSED)
        self.assertIn("[crash_count:1@step:1]", recovered[0].last_error)

    def test_14_crash_recovery_uncertainty_handling(self):
        """Mid-job crash with unfinalized step (success IS NULL) transitions to RETRYING or FAILED."""
        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)

        # Scenario A: attempt_count < max_attempts -> RETRYING
        job_retry = store.create_job(goal="Crash during side-effect tool", status=JobStatus.RUNNING, max_attempts=3)
        job_retry.attempt_count = 1
        store.update_job(job_retry)

        # Unfinalized step (tool started, never completed before crash)
        unfinalized_step = JobStep(
            job_id=job_retry.id,
            attempt=1,
            step_index=1,
            action_type="CALL_TOOL",
            tool_name="run_command",
            success=None,  # Not finalized
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        store.record_step(unfinalized_step)

        mgr = JobManager(store=store)
        recovered_a = mgr.recover_interrupted()

        self.assertEqual(len(recovered_a), 1)
        self.assertEqual(recovered_a[0].status, JobStatus.RETRYING)
        self.assertIn("execution uncertainty detected", recovered_a[0].last_error)

        # Scenario B: attempt_count >= max_attempts -> FAILED
        job_fail = store.create_job(goal="Crash at max attempts", status=JobStatus.RUNNING, max_attempts=2)
        job_fail.attempt_count = 2
        store.update_job(job_fail)

        store.record_step(JobStep(
            job_id=job_fail.id,
            attempt=2,
            step_index=1,
            action_type="CALL_TOOL",
            tool_name="run_command",
            success=None,
            started_at=datetime.now(timezone.utc).isoformat(),
        ))

        recovered_b = mgr.recover_interrupted()
        matching_fail = [j for j in recovered_b if j.id == job_fail.id]
        self.assertEqual(len(matching_fail), 1)
        self.assertEqual(matching_fail[0].status, JobStatus.FAILED)
        self.assertIn("max attempts (2) reached", matching_fail[0].last_error)

    def test_15_crash_recovery_terminal_step_completed(self):
        """Crash after terminal step recorded (FINISH/RESPOND) recovers directly as COMPLETED."""
        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)

        job = store.create_job(goal="Job crashed after finish recorded", status=JobStatus.RUNNING)
        step_terminal = JobStep(
            job_id=job.id,
            attempt=1,
            step_index=1,
            action_type="FINISH",
            success=True,
            result_data_json=json.dumps({"response": "All work was completed before crash."}),
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        store.record_step(step_terminal)

        mgr = JobManager(store=store)
        recovered = mgr.recover_interrupted()

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, JobStatus.COMPLETED)
        self.assertEqual(recovered[0].final_response, "All work was completed before crash.")

    def test_16_repeated_crash_boundary_fails_safely(self):
        """Repeated crashes at the same step boundary (crash_count > 2) bound recovery and mark job FAILED."""
        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)

        job = store.create_job(goal="Crash loop job", status=JobStatus.RUNNING)
        step1 = JobStep(
            job_id=job.id,
            attempt=1,
            step_index=1,
            action_type="CALL_TOOL",
            tool_name="list_files",
            success=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        step2 = JobStep(
            job_id=job.id,
            attempt=1,
            step_index=2,
            action_type="CALL_TOOL",
            tool_name="read_file",
            success=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        store.record_step(step1)
        store.record_step(step2)

        state = AgentState(
            run_id="run_crashed_loop",
            goal=job.goal,
            original_request=job.goal,
            status=AgentStatus.RUNNING,
            step_count=2,
            observations=[{"step": 1, "result": {"success": True}}, {"step": 2, "result": {"success": True}}],
        )
        store.save_checkpoint(job.id, state)

        # Inject previous crash count = 2 at step 2
        job.last_error = "Recovered from process crash: safely paused. [crash_count:2@step:2]"
        store.update_job(job)

        mgr = JobManager(store=store)
        recovered = mgr.recover_interrupted()

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, JobStatus.FAILED)
        self.assertIn("Repeated process crashes detected", recovered[0].last_error)

    def test_16b_startup_crash_recovery_deadlock_resolution(self):
        """A crashed RUNNING job is recovered on startup, unblocking new jobs from deadlock."""
        db_path = resolve_database_path()
        store = JobStore(db_path=db_path)

        # 1. Seed a job stuck in RUNNING from a simulated hard crash
        crashed_job = store.create_job(goal="Interrupted pre-crash job", status=JobStatus.RUNNING)
        step = JobStep(
            job_id=crashed_job.id,
            attempt=1,
            step_index=1,
            action_type="CALL_TOOL",
            tool_name="list_files",
            success=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        store.record_step(step)
        state = AgentState(
            run_id="run_crashed_deadlock",
            goal=crashed_job.goal,
            original_request=crashed_job.goal,
            status=AgentStatus.RUNNING,
            step_count=1,
            observations=[{"step": 1, "action": {"type": "CALL_TOOL"}, "result": {"success": True}}],
        )
        store.save_checkpoint(crashed_job.id, state)

        # Confirm that before recovery, starting a new job would be blocked by concurrency limit
        pre_recovery_mgr = JobManager(store=store)
        blocked_job = pre_recovery_mgr.create("Job attempted while previous is RUNNING")
        blocked_job = pre_recovery_mgr.start(blocked_job.id)
        self.assertEqual(blocked_job.status, JobStatus.PENDING)

        # 2. Simulate adapter boot recovery
        self._reset_engine_state()
        main.ensure_initialized()
        job_mgr = main.get_job_manager()
        recovered = job_mgr.recover_interrupted()
        self.assertTrue(len(recovered) >= 1)

        # Check that the crashed job is now PAUSED, no longer RUNNING
        reloaded_crashed = job_mgr.get_job(crashed_job.id)
        self.assertEqual(reloaded_crashed.status, JobStatus.PAUSED)

        # 3. Verify that a new job can now start without deadlock
        mock_api = MagicMock()
        mock_api.assist.return_value = {
            "reply": json.dumps({"action": {"type": "FINISH", "response": "Unblocked task completed."}}),
            "model": "nvidia/nemotron",
            "success": True,
        }
        main.api_client = mock_api
        if main.agent_engine:
            main.agent_engine.api_client = mock_api

        new_job = job_mgr.create("Post-recovery unblocked job")
        started_job = job_mgr.start(new_job.id)
        self.assertNotEqual(started_job.status, JobStatus.PENDING)
        self.assertIn(started_job.status, (JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.PAUSED))


# =============================================================================
# Pillar 5: Reminders & Restart Survival
# =============================================================================

class TestStage2RemindersAndRestartSurvival(BaseStage2IsolatedTest):
    """Validates reminder scheduling, due event emission, events.ack, and restart deduplication."""

    def test_17_reminder_creation_and_due_emission(self):
        """Due reminders emit reminder.due into proactive_events and mark reminder as fired."""
        # 1. Schedule a reminder with due_at in the past
        past_time = datetime.now() - timedelta(minutes=10)
        rem_id = reminders.add_reminder("Water the office plants", due_at=past_time)
        self.assertGreater(rem_id, 0)

        # 2. Trigger due reminders check
        runtime_adapter._check_and_emit_due_reminders()

        # 3. Verify event recorded in proactive_events
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT event_id, event_type, entity_id, payload_json, acknowledged FROM proactive_events WHERE event_id = ?", (f"evt_reminder_{rem_id}",))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["event_type"], "reminder.due")
            self.assertEqual(row["entity_id"], str(rem_id))
            self.assertEqual(row["acknowledged"], 0)

            # 4. Verify reminder is marked fired in reminders table
            cur.execute("SELECT fired FROM reminders WHERE id = ?", (rem_id,))
            rem_row = cur.fetchone()
            self.assertEqual(rem_row["fired"], 1)

    def test_18_events_ack_and_tick_deduplication(self):
        """Acknowledging proactive event marks acknowledged=1; subsequent worker ticks do NOT duplicate."""
        past_time = datetime.now() - timedelta(minutes=5)
        rem_id = reminders.add_reminder("Submit timesheet", due_at=past_time)
        runtime_adapter._check_and_emit_due_reminders()

        event_id = f"evt_reminder_{rem_id}"

        # 1. Acknowledge via runtime RPC
        ack_res = runtime_adapter.handle_events_ack({"event_id": event_id})
        self.assertTrue(ack_res.get("acknowledged", False))
        self.assertEqual(ack_res.get("rows_affected"), 1)

        # 2. Verify acknowledged status in DB
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT acknowledged, acknowledged_at FROM proactive_events WHERE event_id = ?", (event_id,))
            row = cur.fetchone()
            self.assertEqual(row["acknowledged"], 1)
            self.assertIsNotNone(row["acknowledged_at"])

        # 3. Verify unacknowledged listing excludes acknowledged event
        unacked = runtime_adapter.handle_events_get_unacked({})
        unacked_ids = [e["event_id"] for e in unacked]
        self.assertNotIn(event_id, unacked_ids)

        # 4. Subsequent check tick must not create a duplicate event
        runtime_adapter._check_and_emit_due_reminders()
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as cnt FROM proactive_events WHERE event_id = ?", (event_id,))
            self.assertEqual(cur.fetchone()["cnt"], 1)

    def test_19_reminder_survival_across_process_restart(self):
        """Fired reminders survive process restarts without duplicate emissions; new reminders fire properly."""
        # 1. Create and fire reminder 1
        rem1_id = reminders.add_reminder("Pre-restart reminder", due_at=datetime.now() - timedelta(minutes=5))
        runtime_adapter._check_and_emit_due_reminders()

        # 2. Simulate complete process restart
        self._reset_engine_state()
        mem.initialize_memory()
        runtime_adapter._ensure_stage2c_tables()
        main.ensure_initialized()

        # 3. Worker check on startup must NOT re-emit reminder 1
        runtime_adapter._check_and_emit_due_reminders()
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as cnt FROM proactive_events WHERE event_id = ?", (f"evt_reminder_{rem1_id}",))
            self.assertEqual(cur.fetchone()["cnt"], 1)

        # 4. Schedule new reminder 2 after restart and verify it fires cleanly
        rem2_id = reminders.add_reminder("Post-restart reminder", due_at=datetime.now() - timedelta(minutes=1))
        runtime_adapter._check_and_emit_due_reminders()

        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as cnt FROM proactive_events WHERE event_id = ?", (f"evt_reminder_{rem2_id}",))
            self.assertEqual(cur.fetchone()["cnt"], 1)

    def test_20_reminders_rpc_lifecycle_and_non_firing(self):
        """reminders.create, reminders.list, and reminders.cancel work via JSON-RPC dispatch; cancelled reminders do not fire."""
        # 1. reminders.create via METHOD_REGISTRY
        create_res = runtime_adapter.METHOD_REGISTRY["reminders.create"]({
            "message": "Send project status report",
            "due_at": "2026-11-21T18:00:00",
        })
        self.assertIsInstance(create_res, dict)
        self.assertIn("id", create_res)
        self.assertEqual(create_res["message"], "Send project status report")
        self.assertEqual(create_res["completed"], False)
        rem_id = create_res["id"]

        # 2. reminders.list includes the created reminder
        list_res = runtime_adapter.METHOD_REGISTRY["reminders.list"]({})
        self.assertIsInstance(list_res, list)
        self.assertIn(rem_id, [r["id"] for r in list_res])

        # 3. Create a reminder with due_at in the past
        past_iso = (datetime.now() - timedelta(minutes=15)).isoformat()
        past_rem = runtime_adapter.METHOD_REGISTRY["reminders.create"]({
            "message": "Past cancelled reminder",
            "due_at": past_iso,
        })
        past_rem_id = past_rem["id"]

        # 4. Cancel the past reminder
        cancel_res = runtime_adapter.METHOD_REGISTRY["reminders.cancel"]({"id": past_rem_id})
        self.assertEqual(cancel_res, {"cancelled": True, "id": past_rem_id})

        # 5. Verify cancelled reminder is no longer in pending reminders.list
        list_after_cancel = runtime_adapter.METHOD_REGISTRY["reminders.list"]({})
        self.assertNotIn(past_rem_id, [r["id"] for r in list_after_cancel])

        # 6. Verify that running due reminder checks does NOT emit reminder.due for the cancelled reminder
        runtime_adapter._check_and_emit_due_reminders()
        with runtime_adapter._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as cnt FROM proactive_events WHERE event_id = ?", (f"evt_reminder_{past_rem_id}",))
            self.assertEqual(cur.fetchone()["cnt"], 0)

    def test_21_reminders_rpc_validation_and_completed_filter(self):
        """reminders RPC validates input arguments and include_completed filters fired reminders."""
        # 1. Validation: empty or non-string message
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.create"]({"message": "", "due_at": "2026-11-21T18:00:00"})
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.create"]({"message": "   ", "due_at": "2026-11-21T18:00:00"})

        # 2. Validation: missing or invalid due_at
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.create"]({"message": "Valid message"})
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.create"]({"message": "Valid message", "due_at": "not-a-date"})

        # 3. Validation: cancel requires id or reminder_id
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.cancel"]({})
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.cancel"]({"id": "not-an-int"})
        with self.assertRaises(ValueError):
            runtime_adapter.METHOD_REGISTRY["reminders.cancel"]({"id": 999999})

        # 4. include_completed filter:
        created = runtime_adapter.METHOD_REGISTRY["reminders.create"]({
            "message": "Reminder to be marked completed",
            "due_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
        })
        rem_id = created["id"]
        # Mark fired in database
        reminders.mark_fired(rem_id)

        # Pending list (default / include_completed=False) must NOT include it
        pending_list = runtime_adapter.METHOD_REGISTRY["reminders.list"]({"include_completed": False})
        self.assertNotIn(rem_id, [r["id"] for r in pending_list])

        # All list (include_completed=True) MUST include it with completed=True
        all_list = runtime_adapter.METHOD_REGISTRY["reminders.list"]({"include_completed": True})
        matching = [r for r in all_list if r["id"] == rem_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["completed"], True)

    def test_22_subprocess_runtime_startup_crash_recovery_and_rpc(self):
        """Spawns runtime_adapter.py in a live subprocess, verifying startup crash recovery and reminders RPC."""
        sub_dir = tempfile.mkdtemp(prefix="orange_test_subproc_")
        db_path = os.path.join(sub_dir, "memory.db")
        try:
            # Seed a crashed RUNNING job using JobStore in the isolated database
            store = JobStore(db_path=db_path)
            crashed_job = store.create_job(goal="Subprocess crashed goal", status=JobStatus.RUNNING)
            now_iso = datetime.now(timezone.utc).isoformat()
            step = JobStep(
                job_id=crashed_job.id,
                attempt=1,
                step_index=1,
                action_type="CALL_TOOL",
                tool_name="list_files",
                success=True,
                started_at=now_iso,
                completed_at=now_iso,
            )
            store.record_step(step)
            state = AgentState(
                run_id="run_subproc_crashed",
                goal=crashed_job.goal,
                original_request=crashed_job.goal,
                status=AgentStatus.RUNNING,
                step_count=1,
                observations=[{"step": 1, "action": {"type": "CALL_TOOL"}, "result": {"success": True}}],
            )
            store.save_checkpoint(crashed_job.id, state)
            crashed_id = crashed_job.id

            # Launch runtime_adapter.py in isolated subprocess
            adapter_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "runtime_adapter.py")
            desktop_dir = r"D:\Orange AI\Orange AI Desktop"
            runtime_dir = os.path.dirname(adapter_script)
            env = dict(os.environ)
            env["ORANGE_AI_USER_DATA_DIR"] = sub_dir
            env["ORANGE_AI_TEST_MODE"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["ORANGE_AI_DESKTOP_DIR"] = desktop_dir
            env["PYTHONPATH"] = f"{desktop_dir};{runtime_dir}"

            proc = subprocess.Popen(
                [sys.executable, adapter_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )

            try:
                # 1. First stdout line MUST be runtime.ready
                ready_line = proc.stdout.readline()
                self.assertTrue(ready_line, "Expected runtime.ready frame from adapter stdout")
                ready_msg = json.loads(ready_line)
                self.assertEqual(ready_msg.get("method"), "runtime.ready")

                def send_rpc(method, params=None, req_id=1):
                    msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
                    proc.stdin.write(json.dumps(msg) + "\n")
                    proc.stdin.flush()
                    while True:
                        resp_line = proc.stdout.readline()
                        if not resp_line:
                            raise RuntimeError(f"Subprocess stdout EOF while waiting for response to req_id {req_id}")
                        resp = json.loads(resp_line)
                        if resp.get("id") == req_id:
                            return resp

                # 2. Check that the crashed job was recovered to PAUSED during boot
                status_resp = send_rpc("jobs.status", {"job_id": crashed_id}, req_id=10)
                self.assertIsNotNone(status_resp.get("result"))
                self.assertEqual(status_resp["result"]["status"], "PAUSED")

                # 3. Check reminders.create via JSON-RPC
                create_resp = send_rpc("reminders.create", {"message": "Subprocess reminder", "due_at": "2026-11-21T18:00:00"}, req_id=20)
                self.assertIsNotNone(create_resp.get("result"))
                sub_rem_id = create_resp["result"]["id"]
                self.assertEqual(create_resp["result"]["message"], "Subprocess reminder")

                # 4. Check reminders.list via JSON-RPC
                list_resp = send_rpc("reminders.list", {}, req_id=21)
                self.assertIn(sub_rem_id, [r["id"] for r in list_resp.get("result", [])])

                # 5. Check reminders.cancel via JSON-RPC
                cancel_resp = send_rpc("reminders.cancel", {"id": sub_rem_id}, req_id=22)
                self.assertEqual(cancel_resp.get("result"), {"cancelled": True, "id": sub_rem_id})

                # 6. Clean shutdown
                shutdown_resp = send_rpc("system.shutdown", {}, req_id=99)
                self.assertEqual(shutdown_resp.get("result", {}).get("status"), "shutting_down")
                proc.wait(timeout=5.0)
                self.assertEqual(proc.returncode, 0)
            finally:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                except Exception:
                    pass
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        finally:
            shutil.rmtree(sub_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

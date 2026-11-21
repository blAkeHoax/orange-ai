"""
tests/test_stage3_personal_context.py - Stage 3 Personal Context & Memory Integration Test Suite.

Validates the 4 Stage 3 core deliverables:
1. Bounded active work & workspace state injection in context_budget.py (GAP-3):
   - Injects latest project_reconciliations and active jobs (RUNNING, PAUSED, WAITING_CONFIRMATION)
   - Excludes terminal jobs (COMPLETED, FAILED, CANCELLED)
   - Enforces 300-character active-work cap and 1,500-character total ceiling
   - Never starves Tier 1 (identity) or Tier 2 (active projects)
   - Handles missing tables gracefully (sqlite3.OperationalError safe)
   - Omitted completely when no active work exists (no empty headers)
   - Cleanly injected into chat system_prompt in main.py:process_user_turn
2. Upgraded memory.remember (GAP-5 & GAP-6 backend):
   - Routes structured statements into structured_memories (mode: "structured")
   - Falls back to legacy memories for unstructured notes (mode: "legacy")
   - Preserves backward-compatible {"success": True, "fact": ...} keys
3. Structured memory creation route (memory.create_structured):
   - Validates category, key, value, and confidence in (0.0, 1.0]
   - Persists across simulated process restart
4. Structured memory update route (memory.update):
   - Validates category, key, value
   - Verifies row existence and raises clean error (-32000) on non-existent keys
   - Persists modified value across simulated process restart
"""

import io
import os
import sys
import json
import uuid
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
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
from brain.context_budget import (
    ContextBudgetManager,
    budget_chat_memory,
    build_active_work_summary,
    sanitize_active_work_text,
    DEFAULT_CHAT_BUDGET_CHARS,
)
from brain.jobs.models import Job, JobStatus
from brain.jobs.store import JobStore


class BaseStage3IsolatedTest(unittest.TestCase):
    """Base test class providing strict data isolation and clean state resets."""

    def setUp(self):
        # 1. Dedicated temporary directory for user data
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage3_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        # 2. Reset engine state
        self._reset_engine_state()

        # 3. Initialize database tables in isolated environment
        mem.initialize_memory()
        runtime_adapter._ensure_stage2c_tables()
        main.ensure_initialized()

        self.db_path = os.path.join(self.temp_user_dir, "memory.db")

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
        main.job_store = None
        main.job_runtime = None
        main.job_manager = None
        main.agent_engine = None
        main.history = []


class TestStage3PersonalContext(BaseStage3IsolatedTest):

    def test_01_active_work_injection_with_recon_and_jobs(self):
        """Active work summary injects latest reconciliation and active jobs (RUNNING, PAUSED, WAITING_CONFIRMATION)."""
        conn = mem.get_connection()
        now = datetime.now(timezone.utc).isoformat()

        # Seed project_reconciliations
        conn.execute(
            """
            INSERT INTO project_reconciliations (
                id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                outstanding_items_json, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rec_01", "D:\\Projects\\ZephyrCore", "ZephyrCore", now, "changed",
                "feat/offline-mesh", "c0ffee123", "[]", "[]",
                json.dumps(["core/engine.py", "tests/test_mesh.py"]), "wm_hash_1", "[]", None
            )
        )

        # Seed jobs table directly
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_01", "Compile Rust native module", "RUNNING", 5, now, now)
        )
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_02", "Generate vector embeddings", "PAUSED", 3, now, now)
        )
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_03", "Delete outdated temporary logs", "WAITING_CONFIRMATION", 2, now, now)
        )
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_04", "Initial environment setup", "COMPLETED", 1, now, now)
        )
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_05", "Deprecated sync job", "CANCELLED", 0, now, now)
        )

        # Seed Tier 1 and Tier 2 structured memories
        mem.remember_structured("identity", "name", "Alice", 1.0)
        mem.remember_structured("project", "current", "ZephyrCore", 1.0)
        conn.commit()

        # Run budget_chat_memory
        res = budget_chat_memory(query="what is my current status", max_chars=1500, conn=conn)

        self.assertTrue(bool(res.active_work), "Expected active_work to be non-empty.")
        self.assertIn("ZephyrCore", res.active_work)
        self.assertIn("feat/offline-mesh", res.active_work)
        self.assertIn("changed", res.active_work)
        self.assertIn("2 uncommitted files", res.active_work)

        # Active jobs included
        self.assertIn("[RUNNING] Compile Rust native module", res.active_work)
        self.assertIn("[PAUSED] Generate vector embeddings", res.active_work)
        self.assertIn("[WAITING_CONFIRMATION] Delete outdated temporary logs", res.active_work)

        # Terminal jobs strictly excluded
        self.assertNotIn("Initial environment setup", res.active_work)
        self.assertNotIn("COMPLETED", res.active_work)
        self.assertNotIn("Deprecated sync job", res.active_work)
        self.assertNotIn("CANCELLED", res.active_work)

        # Caps and ceiling enforced
        self.assertLessEqual(len(res.active_work), 300, "Active work must be <= 300 characters.")
        self.assertLessEqual(res.total_chars, 1500, "Total budgeted chars must be <= 1500.")

        # Tier 1 and Tier 2 not starved
        self.assertIn("name: Alice", res.formatted_profile)
        self.assertIn("current: ZephyrCore", res.formatted_profile)

    def test_02_active_work_omitted_when_no_active_data(self):
        """Active work summary is empty ("") when no reconciliations exist and only terminal jobs exist."""
        conn = mem.get_connection()
        mem.remember_structured("identity", "name", "Alice", 1.0)

        # Only completed/failed jobs
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_c1", "Completed build", "COMPLETED", 0, now, now)
        )
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_f1", "Failed build", "FAILED", 0, now, now)
        )
        conn.commit()

        res = budget_chat_memory(query="hello", max_chars=1500, conn=conn)
        self.assertEqual(res.active_work, "")
        self.assertNotIn("ACTIVE WORK", res.active_work)

    def test_03_active_work_defensive_when_tables_missing(self):
        """Context budgeting survives databases where project_reconciliations or jobs table is absent."""
        # Create an isolated connection with only structured_memories
        raw_conn = sqlite3.connect(":memory:")
        raw_conn.execute(
            """
            CREATE TABLE structured_memories (
                id INTEGER PRIMARY KEY,
                category TEXT,
                memory_key TEXT,
                value TEXT,
                confidence REAL,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        raw_conn.execute(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY,
                content TEXT,
                created_at TEXT
            )
            """
        )
        raw_conn.execute("INSERT INTO structured_memories VALUES (1, 'identity', 'name', 'Bob', 1.0, '', '')")
        raw_conn.commit()

        summary = build_active_work_summary(conn=raw_conn, max_chars=300)
        self.assertEqual(summary, "")

        res = budget_chat_memory(query="hello", max_chars=1500, conn=raw_conn)
        self.assertEqual(res.active_work, "")
        self.assertIn("name: Bob", res.formatted_profile)
        raw_conn.close()

    def test_04_active_work_subbudget_cap_and_no_starvation(self):
        """Active work respects 300-char cap and does not starve Tier 1 or Tier 2 under tight budget."""
        conn = mem.get_connection()
        now = datetime.now(timezone.utc).isoformat()

        # Seed reconciliation with clean status
        conn.execute(
            """
            INSERT INTO project_reconciliations (
                id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                outstanding_items_json, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rec_02", "D:\\Projects\\VeryLongProjectNameForTestingPurposes",
                "VeryLongProjectNameForTestingPurposes", now, "clean",
                "feature/extremely-long-branch-name-with-many-hyphens", "abcdef123456", "[]", "[]",
                "[]", "wm_hash_2", "[]", None
            )
        )

        # Seed active job with a 400-char goal
        long_goal = "Analyze the entire codebase and generate a comprehensive architecture report with detailed dependency diagrams " * 4
        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_long", long_goal, "RUNNING", 10, now, now)
        )

        # Seed Tier 1 and Tier 2 facts
        mem.remember_structured("identity", "name", "Charlie", 1.0)
        mem.remember_structured("project", "current", "VeryLongProjectNameForTestingPurposes", 1.0)
        conn.commit()

        # 1. Verify 300-char cap with standard budget
        res_std = budget_chat_memory(conn=conn, max_chars=1500)
        self.assertLessEqual(len(res_std.active_work), 300)

        # 2. Test tight budget (e.g. 250 chars) where Tier 1 & 2 take ~80 chars
        res_tight = budget_chat_memory(conn=conn, max_chars=250)
        self.assertIn("name: Charlie", res_tight.formatted_profile)
        self.assertIn("current: VeryLongProjectNameForTestingPurposes", res_tight.formatted_profile)
        self.assertLessEqual(res_tight.total_chars, 250)

    def test_05_memory_remember_structured_vs_legacy_routing(self):
        """memory.remember classifies structured facts into structured_memories and falls back to legacy memories."""
        # 1. Structured project statement
        res_proj = runtime_adapter.handle_memory_remember({"fact": "I am working on CreatorPulse"})
        self.assertTrue(res_proj["success"])
        self.assertEqual(res_proj["mode"], "structured")
        self.assertEqual(res_proj["fact"], "I am working on CreatorPulse")
        self.assertEqual(len(res_proj["stored"]), 1)
        self.assertEqual(res_proj["stored"][0]["category"], "project")
        self.assertEqual(mem.get_memory("project", "creatorpulse"), "CreatorPulse")

        # 2. Structured contrastive preference statement
        res_pref = runtime_adapter.handle_memory_remember({"fact": "I prefer Vite over Webpack"})
        self.assertTrue(res_pref["success"])
        self.assertEqual(res_pref["mode"], "structured")
        self.assertGreaterEqual(len(res_pref["stored"]), 1)
        self.assertGreaterEqual(len(res_pref["retired"]), 1)
        self.assertEqual(mem.get_memory("preference", "like_vite"), "Vite")

        # 3. Unstructured fact statement (falls back to legacy)
        res_legacy = runtime_adapter.handle_memory_remember({"fact": "The database port is 5432 on localhost"})
        self.assertTrue(res_legacy["success"])
        self.assertEqual(res_legacy["mode"], "legacy")
        self.assertEqual(res_legacy["fact"], "The database port is 5432 on localhost")
        legacy_facts = mem.recall(limit=10)
        self.assertIn("The database port is 5432 on localhost", legacy_facts)

        # 4. Empty fact error
        res_empty = runtime_adapter.handle_memory_remember({"fact": "   "})
        self.assertFalse(res_empty["success"])
        self.assertEqual(res_empty["error"], "Empty fact")

    def test_06_memory_create_structured_validation_and_restart_persistence(self):
        """memory.create_structured validates input and persists across simulated process restart."""
        # Validation checks
        with self.assertRaises(ValueError):
            runtime_adapter.handle_memory_create_structured({"category": "", "key": "k", "value": "v"})

        with self.assertRaises(ValueError):
            runtime_adapter.handle_memory_create_structured({"category": "invalid_cat", "key": "k", "value": "v"})

        with self.assertRaises(ValueError):
            runtime_adapter.handle_memory_create_structured({"category": "tool", "key": "", "value": "v"})

        with self.assertRaises(ValueError):
            runtime_adapter.handle_memory_create_structured({"category": "tool", "key": "k", "value": ""})

        with self.assertRaises(ValueError):
            runtime_adapter.handle_memory_create_structured({"category": "tool", "key": "k", "value": "v", "confidence": 0.0})

        with self.assertRaises(ValueError):
            runtime_adapter.handle_memory_create_structured({"category": "tool", "key": "k", "value": "v", "confidence": 1.5})

        # Valid creation
        res = runtime_adapter.handle_memory_create_structured({
            "category": "tool",
            "key": "rustc",
            "value": "Rust Compiler 1.82",
            "confidence": 0.95
        })
        self.assertTrue(res["success"])
        self.assertEqual(res["memory"]["category"], "tool")
        self.assertEqual(res["memory"]["key"], "rustc")
        self.assertEqual(res["memory"]["value"], "Rust Compiler 1.82")
        self.assertEqual(res["memory"]["confidence"], 0.95)

        # Simulate process restart
        mem.close()
        runtime_adapter._db_conn = None

        val = mem.get_memory("tool", "rustc")
        self.assertEqual(val, "Rust Compiler 1.82")

    def test_07_memory_update_validation_and_restart_persistence(self):
        """memory.update validates input, requires existing key, and persists across restart."""
        # Seed memory
        mem.remember_structured("preference", "like_tea", "Earl Grey", 1.0)
        self.assertEqual(mem.get_memory("preference", "like_tea"), "Earl Grey")

        # Validation: missing key raises ValueError (translating to -32000)
        with self.assertRaises(ValueError) as ctx:
            runtime_adapter.handle_memory_update({
                "category": "preference",
                "key": "nonexistent_tea",
                "value": "Chamomile"
            })
        self.assertIn("not found", str(ctx.exception).lower())

        # Valid update
        res = runtime_adapter.handle_memory_update({
            "category": "preference",
            "key": "like_tea",
            "value": "Darjeeling Green Tea"
        })
        self.assertTrue(res["success"])
        self.assertEqual(res["memory"]["value"], "Darjeeling Green Tea")

        # Simulate process restart
        mem.close()
        runtime_adapter._db_conn = None

        val = mem.get_memory("preference", "like_tea")
        self.assertEqual(val, "Darjeeling Green Tea")

    def test_08_json_rpc_dispatch_wire_contract(self):
        """METHOD_REGISTRY dispatches memory.create_structured, memory.update, and memory.remember."""
        sent_messages = []

        def mock_send_message(payload):
            sent_messages.append(payload)

        with patch.object(runtime_adapter, "send_message", side_effect=mock_send_message):
            # 1. memory.create_structured via dispatch_request
            runtime_adapter.dispatch_request(
                req_id="req_create_1",
                method="memory.create_structured",
                params={"category": "goal", "key": "learn_go", "value": "Build a CLI in Go", "confidence": 0.9}
            )
            self.assertEqual(len(sent_messages), 1)
            resp1 = sent_messages[-1]
            self.assertEqual(resp1.get("id"), "req_create_1")
            self.assertTrue(resp1.get("result", {}).get("success"))

            # 2. memory.update via dispatch_request
            runtime_adapter.dispatch_request(
                req_id="req_update_1",
                method="memory.update",
                params={"category": "goal", "key": "learn_go", "value": "Master Go concurrency patterns"}
            )
            self.assertEqual(len(sent_messages), 2)
            resp2 = sent_messages[-1]
            self.assertEqual(resp2.get("id"), "req_update_1")
            self.assertEqual(resp2.get("result", {}).get("memory", {}).get("value"), "Master Go concurrency patterns")

            # 3. memory.update on non-existent key returns JSON-RPC -32000 error
            runtime_adapter.dispatch_request(
                req_id="req_update_err",
                method="memory.update",
                params={"category": "goal", "key": "nonexistent_key", "value": "val"}
            )
            self.assertEqual(len(sent_messages), 3)
            resp3 = sent_messages[-1]
            self.assertEqual(resp3.get("id"), "req_update_err")
            self.assertIn("error", resp3)
            self.assertEqual(resp3["error"].get("code"), -32000)

            # 4. memory.remember via dispatch_request
            runtime_adapter.dispatch_request(
                req_id="req_rem_1",
                method="memory.remember",
                params={"fact": "I prefer dark mode over light mode"}
            )
            self.assertEqual(len(sent_messages), 4)
            resp4 = sent_messages[-1]
            self.assertEqual(resp4.get("id"), "req_rem_1")
            self.assertEqual(resp4.get("result", {}).get("mode"), "structured")

    def test_09_chat_process_user_turn_injects_active_work(self):
        """main.process_user_turn injects active work summary into outbound chat prompt."""
        conn = mem.get_connection()
        now = datetime.now(timezone.utc).isoformat()

        # Seed reconciliation
        conn.execute(
            """
            INSERT INTO project_reconciliations (
                id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                outstanding_items_json, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rec_09", "D:\\Projects\\PulseEngine", "PulseEngine", now, "changed",
                "feat/audio-dsp", "abc1234", "[]", "[]",
                json.dumps(["dsp/filter.c"]), "wm_hash_9", "[]", None
            )
        )

        conn.execute(
            """
            INSERT INTO jobs (id, goal, status, priority, attempt_count, max_attempts, step_count, retry_delay_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 3, 0, 60, ?, ?)
            """,
            ("job_09", "Benchmark FFT transform", "RUNNING", 5, now, now)
        )
        conn.commit()

        captured_calls = []

        def mock_assist(*args, **kwargs):
            captured_calls.append(kwargs)
            return {"reply": "I see you are working on PulseEngine audio DSP.", "model": "test-model"}

        with patch.object(main.api_client, "assist", side_effect=mock_assist):
            outcome = main.process_user_turn("What is the next step?")
            self.assertEqual(len(captured_calls), 1)
            sys_inst = captured_calls[0].get("system_instruction", "")
            self.assertIn("ACTIVE WORKSPACE & JOBS", sys_inst)
            self.assertIn("PulseEngine", sys_inst)
            self.assertIn("feat/audio-dsp", sys_inst)
            self.assertIn("Benchmark FFT transform", sys_inst)
            self.assertIn("I see you are working on PulseEngine", outcome["reply"])


if __name__ == "__main__":
    unittest.main()

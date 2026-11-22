"""
tests/test_stage5e_skills_rpc.py - Integration & JSON-RPC Test Suite for Stage 5E Orange Skills.

Validates:
1. JSON-RPC skills.* methods:
   - skills.list returns 3 built-in starter skills with risk badges.
   - skills.create validates and stores custom skill.
   - skills.toggle flips enabled status.
   - skills.delete removes custom skills and rejects deleting built-in skills.
   - skills.run executes a skill and returns step results + summary.
2. Chat /skill and /skills commands:
   - /skills lists all enabled skills with badges.
   - /skill <slug> runs the skill and returns skill_used and tool_steps.
   - /skill with unknown slug returns error message.
   - /skill with no arguments returns usage guidance.
3. REA Habit-to-Skill Suggestion:
   - Executing the same 2+ tool sequence across turns triggers outcome["skill_suggestion"].
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch

_test_dir = tempfile.mkdtemp(prefix="orange_test_skills_rpc_")
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
from tools.permissions import set_full_access_mode


class TestStage5ESkillsRPC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ra._is_updating = False
        ra._is_shutting_down = False
        main.ensure_initialized()

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp(prefix="orange_ws_")
        os.environ["ORANGE_ALLOWED_ROOTS"] = f"{_test_dir}{os.pathsep}{self.temp_workspace}{os.pathsep}D:\\Orange AI"
        set_full_access_mode("supervised")
        ra._session_tool_chains.clear()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        set_full_access_mode("supervised")
        ra._session_tool_chains.clear()

    def test_01_skills_list_rpc(self):
        """Verify skills.list returns built-in starter skills with risk levels."""
        skills = ra.handle_skills_list({"user_data_dir": _test_dir})
        self.assertIsInstance(skills, list)
        self.assertGreaterEqual(len(skills), 3)

        slugs = {s["slug"] for s in skills}
        self.assertIn("repo-health-audit", slugs)
        self.assertIn("system-diagnostics", slugs)
        self.assertIn("project-handoff-summary", slugs)

        diag = next(s for s in skills if s["slug"] == "system-diagnostics")
        self.assertEqual(diag["risk_level"], "SAFE")
        self.assertTrue(diag["builtin"])
        self.assertEqual(diag["step_count"], 4)

    def test_02_skills_create_and_toggle_rpc(self):
        """Verify skills.create persists new skill and skills.toggle modifies enabled state."""
        created = ra.handle_skills_create({
            "slug": "custom-cpu-ram",
            "name": "Custom CPU RAM Check",
            "description": "Inspects CPU and RAM.",
            "steps": [
                {"tool": "get_cpu_usage", "args": {}},
                {"tool": "get_ram_usage", "args": {}},
            ],
            "prompt_template": "Resource check report: {{input}}",
            "user_data_dir": _test_dir,
        })
        self.assertEqual(created["slug"], "custom-cpu-ram")
        self.assertFalse(created["builtin"])
        self.assertTrue(created["enabled"])
        self.assertEqual(created["risk_level"], "SAFE")

        # Toggle off
        toggled_off = ra.handle_skills_toggle({
            "slug": "custom-cpu-ram",
            "enabled": False,
            "user_data_dir": _test_dir,
        })
        self.assertFalse(toggled_off["enabled"])

        # Toggle back on (default flip)
        toggled_on = ra.handle_skills_toggle({
            "slug": "custom-cpu-ram",
            "user_data_dir": _test_dir,
        })
        self.assertTrue(toggled_on["enabled"])

    def test_03_skills_delete_protection_rpc(self):
        """Verify custom skills can be deleted while built-in skills reject deletion."""
        # Create disposable custom skill
        ra.handle_skills_create({
            "slug": "deletable-skill",
            "name": "Deletable",
            "steps": [{"tool": "get_date", "args": {}}],
            "user_data_dir": _test_dir,
        })

        # Delete custom skill
        del_res = ra.handle_skills_delete({
            "slug": "deletable-skill",
            "user_data_dir": _test_dir,
        })
        self.assertTrue(del_res.get("deleted"))

        # Attempt to delete built-in skill must fail
        with self.assertRaises(ValueError):
            ra.handle_skills_delete({
                "slug": "system-diagnostics",
                "user_data_dir": _test_dir,
            })

    def test_04_skills_run_rpc(self):
        """Verify skills.run executes the skill and returns structured results."""
        run_res = ra.handle_skills_run({
            "slug": "system-diagnostics",
            "input": "Diagnostic verification",
            "user_data_dir": _test_dir,
        })
        self.assertTrue(run_res["success"])
        self.assertEqual(run_res["status"], "completed")
        self.assertEqual(run_res["slug"], "system-diagnostics")
        self.assertEqual(len(run_res["step_results"]), 4)
        self.assertTrue("CPU" in run_res["output"] or "system" in run_res["output"].lower())

    def test_05_chat_skills_listing_command(self):
        """Verify typing /skills in chat returns markdown list of available skills."""
        outcome = ra.process_user_turn("/skills")
        self.assertEqual(outcome.get("type"), "skill_list")
        self.assertIn("Available Orange Skills", outcome.get("reply", ""))
        self.assertIn("/skill repo-health-audit", outcome.get("reply", ""))
        self.assertIn("/skill system-diagnostics", outcome.get("reply", ""))

    def test_06_chat_skill_execution_command(self):
        """Verify typing /skill <slug> invokes skill and populates skill_used and tool_steps."""
        outcome = ra.process_user_turn("/skill system-diagnostics Live chat check")
        self.assertEqual(outcome.get("type"), "skill")
        self.assertEqual(outcome.get("skill_used"), "system-diagnostics")
        self.assertIsInstance(outcome.get("tool_steps"), list)
        self.assertEqual(len(outcome.get("tool_steps")), 4)
        self.assertTrue("CPU" in outcome.get("reply", "") or "system" in outcome.get("reply", "").lower())

    def test_07_chat_skill_unknown_or_missing(self):
        """Verify /skill with non-existent slug returns friendly error without crashing."""
        outcome = ra.process_user_turn("/skill unknown-skill-xyz")
        self.assertEqual(outcome.get("type"), "skill_not_found")
        self.assertIn("is disabled or not found", outcome.get("reply", ""))

        outcome_empty = ra.process_user_turn("/skill")
        self.assertEqual(outcome_empty.get("type"), "skill_error")
        self.assertIn("Usage:", outcome_empty.get("reply", ""))

    def test_08_rea_habit_to_skill_suggestion(self):
        """Verify repeated 2+ tool sequence across turns triggers skill_suggestion."""
        # First turn executing get_date and get_cpu_usage in multi-step goal loop
        seq = [
            {"reply": 'get_date()', "model": "test"},
            {"reply": 'get_cpu_usage()', "model": "test"},
            {"reply": "System date and CPU usage retrieved.", "model": "test"},
        ]
        seq_idx = 0

        def mock_assist(*args, **kwargs):
            nonlocal seq_idx
            if kwargs.get("task_type") == "structured_output":
                return {"memories": [], "conversational_state": {}}
            res = seq[seq_idx % len(seq)]
            seq_idx += 1
            return res

        with patch.object(main.api_client, "assist", side_effect=mock_assist):
            # Turn 1
            res1 = ra.process_user_turn("Check date and cpu please")
            # First time: sequence recorded once, no suggestion yet
            self.assertNotIn("skill_suggestion", res1)

            # Turn 2: same sequence executed again
            seq_idx = 0
            res2 = ra.process_user_turn("Check date and cpu again please")
            # Second time: repeated sequence detected -> skill_suggestion attached!
            self.assertIn("skill_suggestion", res2)
            suggestion = res2["skill_suggestion"]
            self.assertIn("suggested_slug", suggestion)
            self.assertIn("steps", suggestion)
            self.assertEqual(len(suggestion["steps"]), 2)
            self.assertEqual(suggestion["steps"][0]["tool"], "get_date")
            self.assertEqual(suggestion["steps"][1]["tool"], "get_cpu_usage")


if __name__ == "__main__":
    unittest.main()

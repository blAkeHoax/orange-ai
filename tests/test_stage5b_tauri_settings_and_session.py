"""
tests/test_stage5b_tauri_settings_and_session.py - Stage 5B Tauri Settings and Session Integration Tests.

Validates Stage 5B functionality in Orange AI Tauri runtime:
1. handle_settings_get returns hybrid_memory_extraction_enabled, adaptive_empathy_enabled, and hybrid_memory_confidence_threshold.
2. handle_settings_update correctly persists boolean updates for hybrid memory and adaptive empathy.
3. handle_settings_update rejects non-boolean values for toggle settings.
4. handle_settings_update clamps hybrid_memory_confidence_threshold to [0.5, 1.0] and rejects non-numeric inputs.
5. handle_chat_new_session resets both runtime_adapter._session_conversational_state and main._session_conversational_state.
6. runtime_adapter.process_user_turn propagates conversational_state in outcome and updates adapter session state.
7. conversational_state blends and persists across multiple turns within a session.
"""

import io
import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

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

import runtime_adapter
import main
import brain.memory as mem


class BaseStage5BIsolatedTest(unittest.TestCase):
    """Base test class providing temporary isolated environment."""

    def setUp(self):
        self.temp_user_dir = tempfile.mkdtemp(prefix="orange_test_stage5b_tauri_")
        self.orig_user_data_dir = os.environ.get("ORANGE_AI_USER_DATA_DIR")
        os.environ["ORANGE_AI_USER_DATA_DIR"] = self.temp_user_dir

        self._reset_engine_state()
        mem.initialize_memory()
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
        runtime_adapter._session_conversational_state = None
        if hasattr(main, "reset_session"):
            main.reset_session()
        main.history = []


class TestStage5BTauriSettingsAndSession(BaseStage5BIsolatedTest):

    def test_01_settings_get_default_stage5b_keys(self):
        """handle_settings_get returns default Stage 5B settings with expected types and values."""
        res = runtime_adapter.handle_settings_get({})
        self.assertIn("hybrid_memory_extraction_enabled", res)
        self.assertIn("adaptive_empathy_enabled", res)
        self.assertIn("hybrid_memory_confidence_threshold", res)

        self.assertIsInstance(res["hybrid_memory_extraction_enabled"], bool)
        self.assertTrue(res["hybrid_memory_extraction_enabled"])

        self.assertIsInstance(res["adaptive_empathy_enabled"], bool)
        self.assertTrue(res["adaptive_empathy_enabled"])

        self.assertIsInstance(res["hybrid_memory_confidence_threshold"], float)
        self.assertEqual(res["hybrid_memory_confidence_threshold"], 0.75)

        # Also nested in settings dict
        settings_dict = res.get("settings", {})
        self.assertTrue(settings_dict.get("hybrid_memory_extraction_enabled"))
        self.assertTrue(settings_dict.get("adaptive_empathy_enabled"))
        self.assertEqual(settings_dict.get("hybrid_memory_confidence_threshold"), 0.75)

    def test_02_settings_update_toggle_flags(self):
        """handle_settings_update safely disables and enables hybrid memory and empathy toggles."""
        update_payload = {
            "settings": {
                "hybrid_memory_extraction_enabled": False,
                "adaptive_empathy_enabled": False,
            }
        }
        res = runtime_adapter.handle_settings_update(update_payload)
        self.assertTrue(res.get("success"))
        self.assertFalse(res["settings"]["hybrid_memory_extraction_enabled"])
        self.assertFalse(res["settings"]["adaptive_empathy_enabled"])

        # Re-fetch via handle_settings_get
        get_res = runtime_adapter.handle_settings_get({})
        self.assertFalse(get_res["hybrid_memory_extraction_enabled"])
        self.assertFalse(get_res["adaptive_empathy_enabled"])

        # Re-enable
        enable_res = runtime_adapter.handle_settings_update({
            "settings": {
                "hybrid_memory_extraction_enabled": True,
                "adaptive_empathy_enabled": True,
            }
        })
        self.assertTrue(enable_res.get("success"))
        self.assertTrue(enable_res["settings"]["hybrid_memory_extraction_enabled"])
        self.assertTrue(enable_res["settings"]["adaptive_empathy_enabled"])

    def test_03_settings_update_rejects_non_booleans(self):
        """handle_settings_update rejects non-boolean inputs for hybrid_memory_extraction_enabled and adaptive_empathy_enabled."""
        # Test string representation of bool
        res1 = runtime_adapter.handle_settings_update({
            "settings": {"hybrid_memory_extraction_enabled": "true"}
        })
        self.assertFalse(res1.get("success"))
        self.assertIn("hybrid_memory_extraction_enabled must be a boolean", res1.get("error", ""))

        # Test integer representation of bool
        res2 = runtime_adapter.handle_settings_update({
            "settings": {"adaptive_empathy_enabled": 1}
        })
        self.assertFalse(res2.get("success"))
        self.assertIn("adaptive_empathy_enabled must be a boolean", res2.get("error", ""))

        # Test list
        res3 = runtime_adapter.handle_settings_update({
            "settings": {"hybrid_memory_extraction_enabled": [True]}
        })
        self.assertFalse(res3.get("success"))

    def test_04_settings_update_confidence_threshold_clamping_and_validation(self):
        """handle_settings_update clamps threshold to [0.5, 1.0] and rejects non-numeric values."""
        # Below minimum 0.5 -> clamps to 0.5
        res_low = runtime_adapter.handle_settings_update({
            "settings": {"hybrid_memory_confidence_threshold": 0.2}
        })
        self.assertTrue(res_low.get("success"))
        self.assertEqual(res_low["settings"]["hybrid_memory_confidence_threshold"], 0.5)

        # Above maximum 1.0 -> clamps to 1.0
        res_high = runtime_adapter.handle_settings_update({
            "settings": {"hybrid_memory_confidence_threshold": 1.45}
        })
        self.assertTrue(res_high.get("success"))
        self.assertEqual(res_high["settings"]["hybrid_memory_confidence_threshold"], 1.0)

        # Valid in-range value
        res_mid = runtime_adapter.handle_settings_update({
            "settings": {"hybrid_memory_confidence_threshold": 0.85}
        })
        self.assertTrue(res_mid.get("success"))
        self.assertEqual(res_mid["settings"]["hybrid_memory_confidence_threshold"], 0.85)

        # Non-numeric string -> rejected with error
        res_invalid = runtime_adapter.handle_settings_update({
            "settings": {"hybrid_memory_confidence_threshold": "not_a_number"}
        })
        self.assertFalse(res_invalid.get("success"))
        self.assertIn("hybrid_memory_confidence_threshold must be a float", res_invalid.get("error", ""))

    def test_05_handle_chat_new_session_resets_session_state(self):
        """handle_chat_new_session clears both runtime_adapter and main session states."""
        runtime_adapter._session_conversational_state = {
            "emotional_tone": "frustrated",
            "cognitive_load": "high",
            "preferred_pacing": "brisk",
            "empathy_cue": "Be direct.",
        }
        main._session_conversational_state = {
            "emotional_tone": "frustrated",
            "cognitive_load": "high",
            "preferred_pacing": "brisk",
            "empathy_cue": "Be direct.",
        }

        res = runtime_adapter.handle_chat_new_session({})
        self.assertTrue(res.get("success"))
        self.assertIsNone(runtime_adapter._session_conversational_state)
        self.assertIsNone(main._session_conversational_state)

    def test_06_process_user_turn_returns_conversational_state(self):
        """runtime_adapter.process_user_turn returns conversational_state and updates runtime_adapter._session_conversational_state."""
        with patch.object(main.api_client, "assist") as mock_assist:
            mock_assist.return_value = {
                "reply": "I see the issue in the config file. Let's fix it right now.",
                "model": "nvidia/nemotron-3.5-bolt-e4b",
            }

            outcome = runtime_adapter.process_user_turn("Why is this build failing again?!")

            self.assertIn("conversational_state", outcome)
            state = outcome["conversational_state"]
            self.assertEqual(state.get("emotional_tone"), "frustrated")
            self.assertEqual(state.get("cognitive_load"), "high")
            self.assertEqual(state.get("preferred_pacing"), "direct_fix")
            self.assertEqual(runtime_adapter._session_conversational_state, state)

    def test_07_conversational_state_blending_across_turns(self):
        """Conversational state blends and persists across turns in runtime_adapter."""
        with patch.object(main.api_client, "assist") as mock_assist:
            mock_assist.return_value = {
                "reply": "Understood.",
                "model": "nvidia/nemotron-3.5-bolt-e4b",
            }

            # Turn 1: High frustration
            outcome1 = runtime_adapter.process_user_turn("Ugh! This makes zero sense, nothing is working!")
            self.assertEqual(outcome1["conversational_state"]["emotional_tone"], "frustrated")

            # Turn 2: Brief follow-up (blends prior session state)
            outcome2 = runtime_adapter.process_user_turn("ok")
            self.assertEqual(outcome2["conversational_state"]["emotional_tone"], "frustrated")
            self.assertEqual(runtime_adapter._session_conversational_state["emotional_tone"], "frustrated")


if __name__ == "__main__":
    unittest.main()

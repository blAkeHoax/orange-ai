"""
tests/test_stage4d_chat_tools_and_advisories.py - Regression & Integration Test Suite for Task 4D.

Validates:
1. SAFE Tool Call in Chat (read_file / list_directory):
   - Mock LLM returning read_file(path="...") on a local file.
   - Verifies file is read locally and Chat returns a natural-language response without leaking raw pseudo-code.
2. CONFIRMATION_REQUIRED Tool Call in Chat (create_file / edit_file):
   - Mock LLM returning create_file(path="...", content="...") in a temp directory.
   - Verifies file is NOT created on disk initially, WAITING_CONFIRMATION job is tracked,
     and rejecting leaves disk state completely untouched.
   - Approving creates file on disk and finishes job.
3. HIGH_RISK Tool Call Blocked:
   - Verify HIGH_RISK tool calls (delete_file, format_disk, etc.) in Chat are blocked unconditionally.
4. Clean Ordinary Chat Turn (No Advisory Attachment):
   - Verify ordinary assistant responses return clean text without embedding duplicate advisory cards or contaminating assistant message state.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch

# Configure isolated environment
_test_dir = tempfile.mkdtemp(prefix="orange_test_stage4d_")
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
from tools.permissions import RiskLevel


class TestStage4DChatToolsAndAdvisories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ra._is_updating = False
        ra._is_shutting_down = False
        main.ensure_initialized()

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp(prefix="orange_ws_")
        # Ensure approved roots include test workspace
        os.environ["ORANGE_ALLOWED_ROOTS"] = f"{_test_dir}{os.pathsep}{self.temp_workspace}{os.pathsep}D:\\Orange AI"

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_01_safe_tool_read_file_synthesis_and_no_leak(self):
        """SAFE tool read_file is executed locally and returns grounded response without raw pseudo-code."""
        test_file = os.path.join(self.temp_workspace, "sample.txt")
        file_content = "ALPHA_SECRET_KEY = 'orange-stage4d-verified'\nStatus = Active\n"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(file_content)

        # Mock LLM returning pseudo-function call on the first assist() turn
        # and returning grounded summary on the synthesis assist() turn
        mock_assist_calls = [
            {"reply": f'read_file(path="{test_file}")', "model": "test-llm"},
            {"reply": "The file contains the status 'Active' and the key 'orange-stage4d-verified'.", "model": "test-llm"}
        ]
        
        call_count = 0
        def mock_assist(*args, **kwargs):
            nonlocal call_count
            if kwargs.get("task_type") == "structured_output":
                return {"memories": [], "conversational_state": {}}
            res = mock_assist_calls[min(call_count, len(mock_assist_calls) - 1)]
            call_count += 1
            return res

        with patch.object(main.api_client, "assist", side_effect=mock_assist):
            outcome = ra.process_user_turn(f"Read {test_file} and tell me what is inside.")

        self.assertIn("reply", outcome)
        self.assertNotIn("read_file(", outcome["reply"], "Raw function-call text must not be leaked to the user.")
        self.assertIn("orange-stage4d-verified", outcome["reply"])
        self.assertEqual(outcome.get("type"), "assistant")
        self.assertIsNotNone(outcome.get("tool_result"))
        self.assertEqual(outcome["tool_result"]["tool"], "read_file")

    def test_02_safe_tool_list_directory_synthesis(self):
        """SAFE tool list_directory is executed locally and formatted cleanly."""
        subfile1 = os.path.join(self.temp_workspace, "file_one.py")
        subfile2 = os.path.join(self.temp_workspace, "file_two.json")
        with open(subfile1, "w") as f: f.write("print('1')")
        with open(subfile2, "w") as f: f.write("{}")

        # Mock LLM returning list_directory and synthesis fallback
        with patch.object(main.api_client, "assist", return_value={"reply": f'list_directory(path="{self.temp_workspace}")'}):
            outcome = ra.process_user_turn(f"List files in {self.temp_workspace}")

        self.assertNotIn("list_directory(", outcome["reply"])
        self.assertIn("file_one.py", outcome["reply"])
        self.assertIn("file_two.json", outcome["reply"])

    def test_03_confirmation_required_create_file_rejected_aborts_with_zero_mutations(self):
        """CONFIRMATION_REQUIRED tool create_file pauses for confirmation; rejecting aborts with zero disk mutations."""
        target_path = os.path.join(self.temp_workspace, "guardrail_denied.txt")
        self.assertFalse(os.path.exists(target_path))

        # Mock LLM returning create_file pseudo-code
        mock_reply = f'create_file(path="{target_path}", content="This should never be written")'
        
        prompt_fn = MagicMock(return_value="no")  # User rejects authorization

        with patch.object(main.api_client, "assist", return_value={"reply": mock_reply}):
            outcome = ra.process_user_turn(f"Create a file at {target_path}", prompt_fn=prompt_fn)

        prompt_fn.assert_called_once()
        self.assertFalse(os.path.exists(target_path), "File must NOT be created when authorization is denied.")
        self.assertEqual(outcome.get("status"), "cancelled")
        self.assertIn("not authorized", outcome["reply"].lower())

    def test_04_confirmation_required_create_file_approved_executes(self):
        """CONFIRMATION_REQUIRED tool create_file executes only when approved."""
        target_path = os.path.join(self.temp_workspace, "guardrail_approved.txt")
        self.assertFalse(os.path.exists(target_path))

        mock_reply = f'create_file(path="{target_path}", content="Authorized content verified")'
        prompt_fn = MagicMock(return_value="yes")  # User approves

        with patch.object(main.api_client, "assist", return_value={"reply": mock_reply}):
            outcome = ra.process_user_turn(f"Create file {target_path}", prompt_fn=prompt_fn)

        prompt_fn.assert_called_once()
        self.assertTrue(os.path.exists(target_path), "File MUST be created on disk when authorization is approved.")
        with open(target_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Authorized content verified")
        self.assertEqual(outcome.get("status"), "completed")
        self.assertIn("created successfully", outcome["reply"].lower())

    def test_05_high_risk_tool_call_blocked_unconditionally(self):
        """HIGH_RISK tool call is blocked immediately without executing or prompting."""
        prompt_fn = MagicMock(return_value="yes")

        # Mock LLM proposing delete_file
        mock_reply = 'delete_file(path="C:\\Windows\\System32\\crucial.dll")'
        with patch.object(main.api_client, "assist", return_value={"reply": mock_reply}):
            outcome = ra.process_user_turn("Delete file crucial.dll", prompt_fn=prompt_fn)

        prompt_fn.assert_not_called()
        self.assertEqual(outcome.get("status"), "blocked")
        self.assertIn("high_risk", outcome["reply"].lower())

    def test_06_clean_ordinary_chat_turn_never_attaches_duplicate_advisories(self):
        """Ordinary assistant responses never embed advisory cards or contaminate chat replies."""
        normal_reply = "Here is a normal answer to your question about algorithms."
        # Even if main.process_user_turn appended an advisory string
        contaminated_reply = f"{normal_reply}\n\n💡 **Orange AI Advisory** [MEDIUM]: **Inactivity Advisory: Orange AI**\n   Explanation text\n   *Suggestion:* Action"

        with patch.object(main.api_client, "assist", return_value={"reply": contaminated_reply}):
            outcome = ra.process_user_turn("Explain binary search algorithms to me.")

        self.assertIn(normal_reply, outcome["reply"])
        self.assertNotIn("Orange AI Advisory", outcome["reply"], "Advisory banner must be stripped from ordinary assistant reply.")
        self.assertNotIn("recommendation", outcome, "Ordinary assistant replies must not carry duplicate recommendation cards.")


if __name__ == "__main__":
    unittest.main()

"""
tests/test_stage5f_attachments_rpc.py - Integration & JSON-RPC Test Suite for Stage 5F Attachments.

Validates:
1. JSON-RPC attachments.capture_screen endpoint via METHOD_REGISTRY.
2. chat.send with attachments: local context extraction and prompt injection.
3. Clean conversation history storage: lightweight metadata only, no raw file dump bloat.
4. Empty prompt submission with attachments (defaults to "Analyze the attached file(s).").
5. Hybrid memory extractor safety: inspects clean user prompt, not raw file dumps.
6. Strict text-only API contract preservation: test_api_client_image passes 9/9.
"""

import os
import sys
import json
import base64
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch

_test_dir = tempfile.mkdtemp(prefix="orange_test_attachments_rpc_")
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
import brain.memory as mem


class TestStage5FAttachmentsRPC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ra._is_updating = False
        ra._is_shutting_down = False
        main.ensure_initialized()

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp(prefix="orange_ws_")
        os.environ["ORANGE_ALLOWED_ROOTS"] = f"{_test_dir}{os.pathsep}{self.temp_workspace}{os.pathsep}D:\\Orange AI"

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_01_attachments_capture_screen_rpc(self):
        """Verify attachments.capture_screen RPC handler registered and returns valid metadata."""
        self.assertIn("attachments.capture_screen", ra.METHOD_REGISTRY)
        handler = ra.METHOD_REGISTRY["attachments.capture_screen"]

        res = handler({})
        self.assertIsInstance(res, dict)
        self.assertTrue(res["name"].startswith("screenshot-"))
        self.assertEqual(res["kind"], "screenshot")
        self.assertEqual(res["mime_type"], "image/png")
        self.assertTrue(res["base64_data"].startswith("data:image/png;base64,"))
        self.assertIn("preview_meta", res)

    def test_02_chat_send_context_injection_in_system_prompt(self):
        """Verify attachments are parsed locally and injected into system_instruction without bloating message."""
        code_content = "def calculate_tax(subtotal):\n    return subtotal * 0.08\n"
        att = {
            "name": "tax.py",
            "kind": "code",
            "content": code_content,
        }

        mock_assist_resp = {
            "reply": "The function calculates an 8% tax rate.",
            "model": "nvidia/nemotron-3.5-bolt-e4b",
            "success": True,
        }

        with patch.object(main.api_client, "assist", return_value=mock_assist_resp) as mock_assist:
            from brain.attachments import extract_attachment_context, format_attachments_for_prompt
            extracted = extract_attachment_context(att)
            att_context = format_attachments_for_prompt([extracted])

            outcome = main.process_user_turn(
                user_input="Review this function",
                attachment_context=att_context,
                attachments=[extracted],
            )

            self.assertEqual(outcome["reply"], "The function calculates an 8% tax rate.")
            self.assertIn("attachments", outcome)
            self.assertEqual(outcome["attachments"][0]["name"], "tax.py")

            # Verify conversational assist() call arguments
            conv_call = next(
                c for c in mock_assist.call_args_list
                if c[1].get("task_type") != "structured_output"
            )
            call_kwargs = conv_call[1]
            self.assertEqual(call_kwargs["message"], "Review this function")
            self.assertIn("=== ATTACHED FILES & SCREENSHOTS ===", call_kwargs["system_instruction"])
            self.assertIn("def calculate_tax(subtotal):", call_kwargs["system_instruction"])
            self.assertNotIn("image", call_kwargs)

    def test_03_clean_history_storage_no_dump_bloat(self):
        """Verify conversation_history stores clean prompt text + metadata, NOT raw 10KB dumps."""
        big_content = "LOG_TRACE_DATA " * 600  # ~9,000 chars
        att = {
            "name": "server.log",
            "kind": "file",
            "content": big_content,
        }

        mock_assist_resp = {
            "reply": "Found trace logs.",
            "model": "nvidia/nemotron-3.5-bolt-e4b",
            "success": True,
        }

        with patch.object(main.api_client, "assist", return_value=mock_assist_resp):
            from brain.attachments import extract_attachment_context, format_attachments_for_prompt
            extracted = extract_attachment_context(att)
            att_context = format_attachments_for_prompt([extracted])

            main.process_user_turn(
                user_input="Analyze this crash log",
                attachment_context=att_context,
                attachments=[extracted],
            )

        # Inspect database record
        conn = mem.get_connection()
        cursor = conn.execute(
            "SELECT content FROM conversation_history WHERE role = 'user' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        stored_content = row[0]

        # Verify raw 9,000 char dump is NOT stored in conversation_history
        self.assertNotIn("LOG_TRACE_DATA LOG_TRACE_DATA LOG_TRACE_DATA", stored_content)
        self.assertIn("Analyze this crash log", stored_content)
        self.assertIn("[Attachments:", stored_content)
        self.assertIn("server.log", stored_content)

        # Verify handle_chat_history parses attachments cleanly
        history = ra.handle_chat_history({"limit": 5})
        last_user_turn = next((t for t in reversed(history) if t["role"] == "user"), None)
        self.assertIsNotNone(last_user_turn)
        self.assertEqual(last_user_turn["content"], "Analyze this crash log")
        self.assertIn("attachments", last_user_turn)
        self.assertEqual(last_user_turn["attachments"][0]["name"], "server.log")

    def test_04_empty_prompt_with_attachments_defaults(self):
        """Verify sending attachments with empty prompt text defaults to 'Analyze the attached file(s).'"""
        att = {
            "name": "data.csv",
            "kind": "file",
            "content": "id,val\n1,100\n2,200",
        }

        mock_assist_resp = {
            "reply": "Data contains 2 rows.",
            "model": "nvidia/nemotron-3.5-bolt-e4b",
            "success": True,
        }

        with patch.object(main.api_client, "assist", return_value=mock_assist_resp) as mock_assist:
            from brain.attachments import extract_attachment_context, format_attachments_for_prompt
            extracted = extract_attachment_context(att)
            att_context = format_attachments_for_prompt([extracted])

            outcome = main.process_user_turn(
                user_input="",
                attachment_context=att_context,
                attachments=[extracted],
            )

            self.assertEqual(outcome["reply"], "Data contains 2 rows.")
            conv_call = next(
                c for c in mock_assist.call_args_list
                if c[1].get("task_type") != "structured_output"
            )
            call_kwargs = conv_call[1]
            self.assertEqual(call_kwargs["message"], "Analyze the attached file(s).")

    def test_05_hybrid_memory_extractor_receives_clean_prompt(self):
        """Verify hybrid memory extractor inspects the user message, not raw attachment dumps."""
        att = {
            "name": "notes.md",
            "kind": "file",
            "content": "# Secret Notes\nDo not remember this personal detail.",
        }

        with patch("main.extract_memories_and_state_hybrid") as mock_hybrid, \
             patch.object(main.api_client, "assist", return_value={"reply": "Got it", "model": "test", "success": True}):
            mock_hybrid.return_value = {"memories": [], "conversational_state": None}

            from brain.attachments import extract_attachment_context, format_attachments_for_prompt
            extracted = extract_attachment_context(att)
            att_context = format_attachments_for_prompt([extracted])

            main.process_user_turn(
                user_input="Please summarize these notes",
                attachment_context=att_context,
                attachments=[extracted],
            )

            mock_hybrid.assert_called_once()
            called_user_msg = mock_hybrid.call_args[1]["user_message"]
            self.assertEqual(called_user_msg, "Please summarize these notes")
            self.assertNotIn("Do not remember this personal detail", called_user_msg)

    def test_06_text_only_contract_suite_passes(self):
        """Verify all 9 tests of test_api_client_image.py pass unconditionally."""
        import unittest
        import test_api_client_image

        suite = unittest.TestLoader().loadTestsFromTestCase(test_api_client_image.TestDesktopTextOnlyContract)
        runner = unittest.TextTestRunner(verbosity=0)
        res = runner.run(suite)
        self.assertEqual(len(res.failures), 0)
        self.assertEqual(len(res.errors), 0)
        self.assertEqual(res.testsRun, 9)


if __name__ == "__main__":
    unittest.main()

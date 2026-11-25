"""
test_stage5h_hardening_rpc.py - RPC-level unit tests for v2.1.4 hardening.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

# Ensure paths
tauri_runtime_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runtime"))
desktop_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Orange AI Desktop"))
if tauri_runtime_dir not in sys.path:
    sys.path.insert(0, tauri_runtime_dir)
if desktop_dir not in sys.path:
    sys.path.insert(0, desktop_dir)

import runtime_adapter as ra
from tools.permissions import RiskLevel


class TestStage5HardeningRPC(unittest.TestCase):
    def test_confirmation_cancellation_on_new_session(self):
        conf_id = "test_conf_123"
        conf_event = threading.Event()
        container = {
            "decision": None,
            "event": conf_event,
            "params": {"action": "test"},
        }

        with ra._confirmations_lock:
            ra._pending_confirmations[conf_id] = container

        # Advance session
        res = ra.handle_chat_new_session({})
        self.assertTrue(res.get("success"))

        # Pending confirmation should be cleanly cancelled and event signaled
        self.assertEqual(container["decision"], "no")
        self.assertTrue(conf_event.is_set())
        with ra._confirmations_lock:
            self.assertNotIn(conf_id, ra._pending_confirmations)

    def test_web_search_and_fetch_url_risk_level(self):
        self.assertEqual(ra.get_tool_risk("web_search"), RiskLevel.SAFE)
        self.assertEqual(ra.get_tool_risk("fetch_url"), RiskLevel.SAFE)
        self.assertEqual(ra.get_tool_risk("google"), RiskLevel.SAFE)
        self.assertEqual(ra.get_tool_risk("read_url"), RiskLevel.SAFE)

    def test_web_search_and_url_query_routing(self):
        # 1. Web search query auto-routing
        with patch("runtime_adapter.main.process_user_turn") as mock_turn:
            with patch("runtime_adapter._synthesize_safe_tool_response", return_value="Here is what I found"):
                with patch("brain.api_client.OrangeAPIClient.assist", return_value={"reply": "Done"}):
                    with patch("tools.registry.registry.execute", return_value={"results": []}) as mock_exec:
                        res = ra.process_user_turn("search the web for latest Rust 2024 features")
                        self.assertIn("reply", res)
                        mock_exec.assert_called()
                        call_name = mock_exec.call_args[0][0]
                        self.assertEqual(call_name, "web_search")

        # 2. URL fetch auto-routing
        with patch("runtime_adapter.main.process_user_turn") as mock_turn:
            with patch("runtime_adapter._synthesize_safe_tool_response", return_value="Here is page summary"):
                with patch("brain.api_client.OrangeAPIClient.assist", return_value={"reply": "Done"}):
                    with patch("tools.registry.registry.execute", return_value={"title": "Test", "content": "Hello"}) as mock_exec:
                        res = ra.process_user_turn("summarize this page: https://example.com/blog")
                        self.assertIn("reply", res)
                        mock_exec.assert_called()
                        call_name = mock_exec.call_args[0][0]
                        self.assertEqual(call_name, "fetch_url")


if __name__ == "__main__":
    unittest.main()

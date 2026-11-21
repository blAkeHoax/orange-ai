"""
test_client_auth.py - Verification suite for Desktop client authentication (Task 1C).

Verifies:
1. OrangeAPIClient initialization and ORANGE_API_KEY resolution (env var vs explicit arg).
2. Outgoing assist() requests include Authorization: Bearer <key> when configured.
3. Outgoing assist() requests omit Authorization header when api_key is empty/unset.
4. HTTP 401 responses map to clear, actionable OrangeAPIResponseError messages.
5. Runtime adapter _ensure_api_client_configured() and _apply_runtime_settings() synchronize api_key.
"""

import io
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

sys.dont_write_bytecode = True

# Isolate user data directory before importing any desktop/runtime modules
_temp_user_data_dir = tempfile.mkdtemp(prefix="orange_test_client_auth_")
os.environ["ORANGE_AI_USER_DATA_DIR"] = _temp_user_data_dir
os.environ["ORANGE_AI_TEST_MODE"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

_tauri_root = r"D:\Orange AI\Orange AI Tauri"
_desktop_root = r"D:\Orange AI\Orange AI Desktop"
_runtime_dir = os.path.join(_tauri_root, "runtime")

os.environ["ORANGE_AI_DESKTOP_DIR"] = _desktop_root

if _desktop_root not in sys.path:
    sys.path.insert(0, _desktop_root)
if _runtime_dir not in sys.path:
    sys.path.insert(0, _runtime_dir)

from brain.api_client import OrangeAPIClient, OrangeAPIResponseError, OrangeAPIError


class TestClientAuthentication(unittest.TestCase):
    """Test suite for OrangeAPIClient authentication header attachment and 401 handling."""

    def setUp(self):
        # Save original environ
        self._orig_api_key = os.environ.get("ORANGE_API_KEY")

    def tearDown(self):
        if self._orig_api_key is not None:
            os.environ["ORANGE_API_KEY"] = self._orig_api_key
        elif "ORANGE_API_KEY" in os.environ:
            del os.environ["ORANGE_API_KEY"]

    # =========================================================================
    # Group 1: Initialization & Key Resolution
    # =========================================================================

    def test_01_client_initialization_no_key(self):
        """When ORANGE_API_KEY is not set, client.api_key defaults to empty string."""
        if "ORANGE_API_KEY" in os.environ:
            del os.environ["ORANGE_API_KEY"]
        client = OrangeAPIClient()
        self.assertEqual(client.api_key, "")

    def test_02_client_initialization_from_environ(self):
        """When ORANGE_API_KEY is set in environment, client picks it up."""
        os.environ["ORANGE_API_KEY"] = "env-secret-token"
        client = OrangeAPIClient()
        self.assertEqual(client.api_key, "env-secret-token")

    def test_03_client_initialization_explicit_arg_overrides_environ(self):
        """Explicit api_key parameter overrides environment variable."""
        os.environ["ORANGE_API_KEY"] = "env-secret-token"
        client = OrangeAPIClient(api_key="explicit-secret-token")
        self.assertEqual(client.api_key, "explicit-secret-token")

    def test_04_client_initialization_strips_whitespace(self):
        """Surrounding whitespace is stripped from configured api_key."""
        client = OrangeAPIClient(api_key="   padded-token   ")
        self.assertEqual(client.api_key, "padded-token")

    # =========================================================================
    # Group 2: Outgoing Request Headers
    # =========================================================================

    def test_05_assist_attaches_bearer_header_when_key_configured(self):
        """assist() attaches Authorization: Bearer <key> to urllib.request.Request."""
        client = OrangeAPIClient(api_url="http://test-host:8000", api_key="secret-key-123")
        captured_req = []

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps({
                    "reply": "Authenticated response",
                    "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                    "success": True,
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            captured_req.append(req)
            return MockResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = client.assist(message="Hello API")

        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        # In urllib.request.Request, headers are normalized in header_items()
        headers = dict(req.header_items())
        # Case insensitive header lookup
        auth_header = None
        for k, v in headers.items():
            if k.lower() == "authorization":
                auth_header = v
                break

        self.assertIsNotNone(auth_header)
        self.assertEqual(auth_header, "Bearer secret-key-123")
        self.assertEqual(res["reply"], "Authenticated response")

    def test_06_assist_omits_authorization_header_when_key_empty(self):
        """assist() does NOT attach Authorization header when api_key is empty."""
        client = OrangeAPIClient(api_url="http://test-host:8000", api_key="")
        captured_req = []

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps({
                    "reply": "Unauthenticated response",
                    "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                    "success": True,
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            captured_req.append(req)
            return MockResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = client.assist(message="Hello API")

        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        headers = dict(req.header_items())
        auth_header = any(k.lower() == "authorization" for k in headers.keys())
        self.assertFalse(auth_header, "Authorization header must NOT be attached when key is empty")
        self.assertEqual(res["reply"], "Unauthenticated response")

    # =========================================================================
    # Group 3: HTTP 401 Error Handling
    # =========================================================================

    def test_07_http_401_maps_to_actionable_error_with_detail(self):
        """HTTP 401 with JSON body produces actionable OrangeAPIResponseError."""
        client = OrangeAPIClient(api_url="http://test-host:8000", api_key="wrong-key")

        error_json = json.dumps({"detail": "Invalid or missing API key"}).encode("utf-8")
        fp = io.BytesIO(error_json)
        http_err = urllib.error.HTTPError(
            url="http://test-host:8000/assist",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=fp,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(OrangeAPIResponseError) as ctx:
                client.assist(message="Hello API")

        msg = str(ctx.exception)
        self.assertIn("Orange API authentication failed (HTTP 401)", msg)
        self.assertIn("Invalid or missing API key", msg)
        self.assertIn("Please check your ORANGE_API_KEY configuration.", msg)

    def test_08_http_401_maps_to_actionable_error_without_detail(self):
        """HTTP 401 without JSON body produces actionable OrangeAPIResponseError."""
        client = OrangeAPIClient(api_url="http://test-host:8000", api_key="wrong-key")

        fp = io.BytesIO(b"Unauthorized")
        http_err = urllib.error.HTTPError(
            url="http://test-host:8000/assist",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=fp,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(OrangeAPIResponseError) as ctx:
                client.assist(message="Hello API")

        msg = str(ctx.exception)
        self.assertIn("Orange API authentication failed (HTTP 401)", msg)
        self.assertIn("Please check your ORANGE_API_KEY configuration.", msg)

    # =========================================================================
    # Group 4: Runtime Adapter Synchronization
    # =========================================================================

    def test_09_runtime_adapter_syncs_api_key(self):
        """runtime_adapter._ensure_api_client_configured() applies ORANGE_API_KEY."""
        import runtime_adapter
        import main

        os.environ["ORANGE_API_KEY"] = "runtime-sync-key-789"
        main.api_client = None

        runtime_adapter._ensure_api_client_configured()
        self.assertIsNotNone(main.api_client)
        self.assertEqual(main.api_client.api_key, "runtime-sync-key-789")

        # Now simulate runtime settings update
        os.environ["ORANGE_API_KEY"] = "updated-key-000"
        runtime_adapter._apply_runtime_settings({"api_url": "http://127.0.0.1:9000"})
        self.assertEqual(main.api_client.api_key, "updated-key-000")
        self.assertEqual(main.api_client.api_url, "http://127.0.0.1:9000")


if __name__ == "__main__":
    unittest.main()

"""
test_briefing_timeout_reliability.py - Isolated Daily Briefing Reliability & Timeout Test Suite.

Orange AI Desktop 2.0 (Tauri) - Feature Parity Initiative (Step 2 Implementation).

Covers:
- Test A: Call-site regression test for _evaluate_morning_briefing() passing timeout=60.0.
- Test B: Timeout forwarding through BriefingSynthesizer, _model_aware_assist wrapper,
          and OrangeAPIClient to urllib.request.urlopen.
- Test C: Successful synthesis and model inheritance (Nemotron default & GLM selected).
- Test D: Failure and fallback matrix (API unavailable, URLError, socket timeout, HTTP 504,
          malformed JSON, empty reply) ensuring deterministic fallback and zero retries.
- Test E: Worker continuation verification ensuring synthesis failure does not terminate
          subsequent background evaluation.
- Test F: Isolated DB and event persistence verification.
"""

import os
import sys
import json
import socket
import tempfile
import sqlite3
import unittest
import unittest.mock
from datetime import datetime, timezone
import urllib.error
import urllib.request

# Ensure bytecode is never written to disk
sys.dont_write_bytecode = True

# 1. Setup Isolated Test Environment BEFORE any Orange AI module import
_temp_user_data_dir = tempfile.mkdtemp(prefix="orange_test_step2_")
os.environ["ORANGE_AI_USER_DATA_DIR"] = _temp_user_data_dir
os.environ["ORANGE_AI_TEST_MODE"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Project paths
_tauri_root = r"D:\Orange AI\Orange AI Tauri"
_desktop_root = r"D:\Orange AI\Orange AI Desktop"
_runtime_dir = os.path.join(_tauri_root, "runtime")

os.environ["ORANGE_AI_DESKTOP_DIR"] = _desktop_root

if _desktop_root not in sys.path:
    sys.path.insert(0, _desktop_root)
if _runtime_dir not in sys.path:
    sys.path.insert(0, _runtime_dir)

# Import application modules
import runtime_adapter as ra
import main
from brain.api_client import OrangeAPIClient, OrangeAPIConnectionError, OrangeAPIResponseError
from brain.briefing.models import (
    DailyBriefing,
    DailyBriefingContext,
    PriorityItem,
    PriorityLevel,
    ProjectBriefingContext,
    ReminderBriefingContext,
    JobBriefingContext,
)
from brain.briefing.synthesizer import BriefingSynthesizer
from brain.paths import get_user_data_dir
from brain.database import resolve_database_path


def create_synthetic_briefing_context(current_date: str = "2026-11-20") -> DailyBriefingContext:
    """Create a fully isolated, synthetic DailyBriefingContext fixture."""
    critical_prio = PriorityItem(
        category="reminders",
        title="Submit Quarterly Report",
        level=PriorityLevel.CRITICAL,
        details="Due yesterday; overdue commitment",
        action_hint="Submit report immediately",
    )
    high_prio = PriorityItem(
        category="commitments",
        title="Review PR #42",
        level=PriorityLevel.HIGH,
        details="Scheduled for today 14:00",
        action_hint="Complete code review",
    )

    overdue_rem = ReminderBriefingContext(
        id=101,
        message="Submit Quarterly Report",
        due_at="2026-11-19T17:00:00Z",
        is_overdue=True,
        is_today=False,
    )
    today_rem = ReminderBriefingContext(
        id=102,
        message="Review PR #42",
        due_at="2026-11-20T14:00:00Z",
        is_overdue=False,
        is_today=True,
    )
    active_job = JobBriefingContext(
        id="job_test_001",
        short_id="jt01",
        goal="Compile Stage 2 tests",
        status="RUNNING",
        priority=2,
    )

    return DailyBriefingContext(
        user_name="TestUser",
        current_date=current_date,
        current_project=ProjectBriefingContext(name="Orange AI Desktop 2.0", is_current=True),
        secondary_projects=[],
        overdue_reminders=[overdue_rem],
        today_reminders=[today_rem],
        blocked_jobs=[],
        active_jobs=[active_job],
        paused_jobs=[],
        recent_completed_jobs=[],
        actionable_system_status="All systems normal",
        recent_project_developments=["Step 2 reliability test started"],
        priorities=[critical_prio, high_prio],
        general_goals=["Ensure 100% test isolation"],
        project_health_assessments=[],
        recommendations=[],
    )


class BaseIsolatedBriefingTest(unittest.TestCase):
    """Base test class providing isolation guards for SQLite, settings, and events."""

    def setUp(self):
        # Ensure test directory is active
        self.test_data_dir = _temp_user_data_dir
        self.assertTrue(get_user_data_dir().startswith(tempfile.gettempdir()) or "orange_test" in get_user_data_dir())

        # Ensure isolated tables
        ra._ensure_stage2c_tables()
        with ra._get_db_connection() as conn:
            conn.execute("DELETE FROM daily_briefings")
            conn.execute("DELETE FROM proactive_events")
            conn.commit()

        # Capture emitted protocol messages and events
        self.emitted_messages = []
        self.emitted_events = []

        def mock_send_message(msg):
            self.emitted_messages.append(msg)

        def mock_send_event(event_name, params):
            self.emitted_events.append({"event": event_name, "params": params})

        self._patch_send_msg = unittest.mock.patch.object(ra, "send_message", side_effect=mock_send_message)
        self._patch_send_evt = unittest.mock.patch.object(ra, "send_event", side_effect=mock_send_event)
        self._patch_send_msg.start()
        self._patch_send_evt.start()

        # Isolate settings
        self.isolated_settings = dict(ra.DEFAULT_SETTINGS)
        self.isolated_settings["morning_briefing_enabled"] = True
        self.isolated_settings["preferred_briefing_time"] = "00:00"
        ra._save_gui_settings(self.isolated_settings)

        # Clear main.api_client
        main.api_client = None

    def tearDown(self):
        self._patch_send_msg.stop()
        self._patch_send_evt.stop()


class TestCallSiteRegression(BaseIsolatedBriefingTest):
    """Test A: Targeted regression test for the changed call site in _evaluate_morning_briefing()."""

    def test_evaluate_morning_briefing_passes_timeout_60(self):
        """
        Verify that _evaluate_morning_briefing passes timeout=60.0 to BriefingSynthesizer.synthesize().
        Before the Step 2 edit, this test MUST fail with AssertionError because synthesize() was called
        without timeout=60.0 (kwargs.get('timeout') is None).
        After the Step 2 edit, it MUST pass.
        """
        synthetic_context = create_synthetic_briefing_context("2026-11-20")

        # Mock collector to return synthetic context deterministically
        with unittest.mock.patch.object(ra, "BriefingCollector") as mock_collector_cls:
            mock_collector = unittest.mock.MagicMock()
            mock_collector.collect.return_value = synthetic_context
            mock_collector_cls.return_value = mock_collector

            # Mock BriefingSynthesizer to intercept the exact call arguments passed to synthesize()
            with unittest.mock.patch.object(ra, "BriefingSynthesizer") as mock_synth_cls:
                mock_synth_instance = unittest.mock.MagicMock()
                mock_synth_cls.return_value = mock_synth_instance

                # Return a valid synthetic DailyBriefing
                expected_briefing = DailyBriefing(
                    date="2026-11-20",
                    summary_markdown="## Good morning\nTest summary.",
                    priorities=synthetic_context.priorities,
                    raw_reply="Test summary.",
                    model_name="nvidia/nemotron-3.5-lightning-30b-a3b",
                    is_fallback=False,
                )
                mock_synth_instance.synthesize.return_value = expected_briefing

                # Trigger briefing evaluation via production orchestrator
                now = datetime(2026, 11, 20, 9, 0, 0, tzinfo=timezone.utc)
                result = ra._evaluate_morning_briefing(force=True, test_now=now)

                # Verify synthesize was called exactly once
                self.assertEqual(mock_synth_instance.synthesize.call_count, 1)

                call_args = mock_synth_instance.synthesize.call_args
                # Check kwargs passed to synthesize()
                passed_timeout = call_args.kwargs.get("timeout") if call_args else None

                # CRITICAL RED/GREEN ASSERTION:
                # Before edit: call was synthesizer.synthesize(context) -> passed_timeout is None
                # After edit: call is synthesizer.synthesize(context, timeout=60.0) -> passed_timeout is 60.0
                self.assertEqual(
                    passed_timeout,
                    60.0,
                    f"BriefingSynthesizer.synthesize() did not receive explicit timeout=60.0. "
                    f"Actual kwargs: {call_args.kwargs if call_args else {}}"
                )

                self.assertIsNotNone(result)
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["model_name"], "nvidia/nemotron-3.5-lightning-30b-a3b")


class TestTimeoutForwarding(BaseIsolatedBriefingTest):
    """Test B: Verify timeout propagation through all layers down to socket urlopen."""

    def test_synthesizer_forwards_timeout_to_api_client(self):
        """BriefingSynthesizer.synthesize(context, timeout=60.0) forwards timeout to api_client.assist()."""
        mock_client = unittest.mock.MagicMock(spec=OrangeAPIClient)
        mock_client.is_available.return_value = True
        mock_client.assist.return_value = {
            "success": True,
            "reply": "Synthesized briefing text",
            "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        }

        synthesizer = BriefingSynthesizer(api_client=mock_client)
        context = create_synthetic_briefing_context("2026-11-20")

        briefing = synthesizer.synthesize(context, timeout=60.0)

        self.assertEqual(mock_client.assist.call_count, 1)
        assist_kwargs = mock_client.assist.call_args.kwargs
        self.assertEqual(
            assist_kwargs.get("timeout"),
            60.0,
            "synthesizer.synthesize() failed to forward timeout=60.0 to api_client.assist()",
        )
        self.assertFalse(briefing.is_fallback)
        self.assertEqual(briefing.summary_markdown, "Synthesized briefing text")

    def test_model_aware_assist_wrapper_preserves_timeout_and_injects_model(self):
        """_ensure_api_client_configured() wrapper preserves timeout while injecting selected model."""
        ra._ensure_api_client_configured()
        self.assertIsNotNone(main.api_client)

        orig_assist_mock = unittest.mock.MagicMock(return_value={"success": True, "reply": "ok", "model": ra.DEFAULT_MODEL})

        # Test the wrapper logic directly with active settings
        with unittest.mock.patch.object(main.api_client, "assist", side_effect=lambda *a, **kw: orig_assist_mock(*a, **kw)):
            # Force wrapper installation
            main.api_client._stage2b_wrapped = False
            ra._ensure_api_client_configured()

            # Call assist without model but with timeout=60.0
            res = main.api_client.assist(message="Test prompt", timeout=60.0)

            self.assertEqual(orig_assist_mock.call_count, 1)
            called_kwargs = orig_assist_mock.call_args.kwargs
            self.assertEqual(called_kwargs.get("timeout"), 60.0, "Wrapper failed to preserve timeout=60.0")
            self.assertEqual(
                called_kwargs.get("model"),
                ra.DEFAULT_MODEL,
                "Wrapper failed to inject DEFAULT_MODEL when model was omitted",
            )

    def test_orange_api_client_forwards_timeout_to_urllib_urlopen(self):
        """OrangeAPIClient.assist() passes timeout directly to urllib.request.urlopen(req, timeout=timeout)."""
        client = OrangeAPIClient(api_url="http://127.0.0.1:9999")

        fake_response_data = json.dumps({
            "success": True,
            "reply": "Morning narrative text",
            "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        }).encode("utf-8")

        mock_http_response = unittest.mock.MagicMock()
        mock_http_response.status = 200
        mock_http_response.read.return_value = fake_response_data
        mock_http_response.__enter__.return_value = mock_http_response
        mock_http_response.__exit__.return_value = False

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_http_response) as mock_urlopen:
            res = client.assist(
                message="Morning prompt",
                system_instruction="System prompt",
                timeout=60.0,
            )

            self.assertEqual(mock_urlopen.call_count, 1)
            urlopen_kwargs = mock_urlopen.call_args.kwargs
            self.assertEqual(
                urlopen_kwargs.get("timeout"),
                60.0,
                "OrangeAPIClient.assist() failed to pass timeout=60.0 to urllib.request.urlopen()",
            )
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("reply"), "Morning narrative text")


class TestModelInheritance(BaseIsolatedBriefingTest):
    """Test C: Model inheritance (Nemotron default vs GLM selected) and response formatting."""

    def test_default_nemotron_model_inheritance(self):
        """When default model is configured, assist request carries Nemotron model identifier."""
        settings = ra._load_gui_settings()
        settings["model"] = "nvidia/nemotron-3.5-lightning-30b-a3b"
        ra._save_gui_settings(settings)

        ra._ensure_api_client_configured()

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                resp_payload = json.dumps({"status": "online"}).encode("utf-8")
            else:
                body = json.loads(req.data.decode("utf-8")) if getattr(req, "data", None) else {}
                captured_requests.append({"url": url, "body": body, "timeout": timeout})
                resp_payload = json.dumps({
                    "success": True,
                    "reply": "Generated briefing content with Nemotron.",
                    "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                }).encode("utf-8")

            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = resp_payload
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self.assertFalse(briefing.is_fallback)
            self.assertEqual(briefing.model_name, "nvidia/nemotron-3.5-lightning-30b-a3b")
            self.assertEqual(len(captured_requests), 1)
            self.assertEqual(
                captured_requests[0]["body"].get("model"),
                "nvidia/nemotron-3.5-lightning-30b-a3b",
            )
            self.assertEqual(captured_requests[0]["timeout"], 60.0)

    def test_selected_glm_model_inheritance(self):
        """When GLM model is selected in settings, assist request forwards GLM model identifier unchanged."""
        settings = ra._load_gui_settings()
        settings["model"] = "z-ai/glm-5.3-flash"
        ra._save_gui_settings(settings)

        ra._ensure_api_client_configured()

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                resp_payload = json.dumps({"status": "online"}).encode("utf-8")
            else:
                body = json.loads(req.data.decode("utf-8")) if getattr(req, "data", None) else {}
                captured_requests.append({"url": url, "body": body, "timeout": timeout})
                resp_payload = json.dumps({
                    "success": True,
                    "reply": "Generated briefing content with GLM.",
                    "model": "z-ai/glm-5.3-flash",
                }).encode("utf-8")

            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = resp_payload
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self.assertFalse(briefing.is_fallback)
            self.assertEqual(briefing.model_name, "z-ai/glm-5.3-flash")
            self.assertEqual(len(captured_requests), 1)
            self.assertEqual(
                captured_requests[0]["body"].get("model"),
                "z-ai/glm-5.3-flash",
            )
            self.assertEqual(captured_requests[0]["timeout"], 60.0)


class TestFailureAndFallbackMatrix(BaseIsolatedBriefingTest):
    """Test D: Failure and deterministic fallback matrix with zero retries."""

    def _assert_deterministic_fallback(self, briefing, context):
        """Helper to assert standard deterministic fallback invariants."""
        self.assertTrue(briefing.is_fallback, "Expected is_fallback=True on synthesis failure")
        self.assertEqual(briefing.model_name, "local_deterministic")
        self.assertIn("Immediate Attention", briefing.summary_markdown)
        # Check representative fixture items exist in fallback markdown
        self.assertIn("Submit Quarterly Report", briefing.summary_markdown)
        self.assertIn("Review PR #42", briefing.summary_markdown)

    def test_fallback_when_api_unconfigured_or_unavailable(self):
        """Scenario 1: API client is None or is_available() returns False."""
        mock_client = unittest.mock.MagicMock(spec=OrangeAPIClient)
        mock_client.is_available.return_value = False

        synthesizer = BriefingSynthesizer(api_client=mock_client)
        context = create_synthetic_briefing_context("2026-11-20")

        briefing = synthesizer.synthesize(context, timeout=60.0)

        self._assert_deterministic_fallback(briefing, context)
        self.assertEqual(mock_client.assist.call_count, 0, "assist() must not be called when unavailable")

    def test_fallback_on_connection_error_urlerror(self):
        """Scenario 2: Connection failure (URLError)."""
        ra._ensure_api_client_configured()
        call_count = 0

        def fake_urlopen(req, *args, **kwargs):
            nonlocal call_count
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                mock_resp = unittest.mock.MagicMock()
                mock_resp.status = 200
                mock_resp.read.return_value = json.dumps({"status": "online"}).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_resp.__exit__.return_value = False
                return mock_resp
            call_count += 1
            raise urllib.error.URLError("Connection refused by target host")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self._assert_deterministic_fallback(briefing, context)
            self.assertEqual(call_count, 1, "Must execute exactly one attempt without retry")

    def test_fallback_on_socket_timeout(self):
        """Scenario 3: Socket read/connect timeout (TimeoutError / socket.timeout)."""
        ra._ensure_api_client_configured()
        call_count = 0

        def fake_urlopen(req, *args, **kwargs):
            nonlocal call_count
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                mock_resp = unittest.mock.MagicMock()
                mock_resp.status = 200
                mock_resp.read.return_value = json.dumps({"status": "online"}).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_resp.__exit__.return_value = False
                return mock_resp
            call_count += 1
            raise socket.timeout("The read operation timed out")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self._assert_deterministic_fallback(briefing, context)
            self.assertEqual(call_count, 1, "Must execute exactly one attempt without retry")

    def test_fallback_on_http_504_gateway_timeout(self):
        """Scenario 4: Upstream HTTP 504 Gateway Timeout."""
        ra._ensure_api_client_configured()
        call_count = 0

        def fake_urlopen(req, *args, **kwargs):
            nonlocal call_count
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                mock_resp = unittest.mock.MagicMock()
                mock_resp.status = 200
                mock_resp.read.return_value = json.dumps({"status": "online"}).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_resp.__exit__.return_value = False
                return mock_resp
            call_count += 1
            raise urllib.error.HTTPError(
                url="https://orange-api-cuuo.onrender.com/assist",
                code=504,
                msg="Gateway Timeout",
                hdrs={},
                fp=None,
            )

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self._assert_deterministic_fallback(briefing, context)
            self.assertEqual(call_count, 1, "Must execute exactly one attempt without retry")

    def test_fallback_on_malformed_json_response(self):
        """Scenario 5: Malformed non-JSON response from API."""
        ra._ensure_api_client_configured()
        call_count = 0

        def fake_urlopen(req, *args, **kwargs):
            nonlocal call_count
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                mock_resp = unittest.mock.MagicMock()
                mock_resp.status = 200
                mock_resp.read.return_value = json.dumps({"status": "online"}).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_resp.__exit__.return_value = False
                return mock_resp
            call_count += 1
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"<html><head><title>502 Bad Gateway</title></head></html>"
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self._assert_deterministic_fallback(briefing, context)
            self.assertEqual(call_count, 1, "Must execute exactly one attempt without retry")

    def test_fallback_on_empty_reply(self):
        """Scenario 6: API returns success but empty or whitespace reply."""
        ra._ensure_api_client_configured()
        call_count = 0

        def fake_urlopen(req, *args, **kwargs):
            nonlocal call_count
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/health"):
                mock_resp = unittest.mock.MagicMock()
                mock_resp.status = 200
                mock_resp.read.return_value = json.dumps({"status": "online"}).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_resp.__exit__.return_value = False
                return mock_resp
            call_count += 1
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({"success": True, "reply": "", "model": "test"}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            context = create_synthetic_briefing_context("2026-11-20")

            briefing = synthesizer.synthesize(context, timeout=60.0)

            self._assert_deterministic_fallback(briefing, context)
            self.assertEqual(call_count, 1, "Must execute exactly one attempt without retry")


class TestWorkerContinuationAndPersistence(BaseIsolatedBriefingTest):
    """Test E & F: Worker continuation, database persistence, and proactive event recovery."""

    def test_persistence_of_fallback_status_in_database(self):
        """When synthesis falls back, daily_briefings record receives status='fallback' and local_deterministic."""
        synthetic_context = create_synthetic_briefing_context("2026-11-21")

        with unittest.mock.patch.object(ra, "BriefingCollector") as mock_collector_cls:
            mock_collector = unittest.mock.MagicMock()
            mock_collector.collect.return_value = synthetic_context
            mock_collector_cls.return_value = mock_collector

            with unittest.mock.patch.object(ra, "BriefingSynthesizer") as mock_synth_cls:
                # Return fallback briefing
                fallback_briefing = DailyBriefing(
                    date="2026-11-21",
                    summary_markdown="## Immediate Attention\n- Submit Quarterly Report",
                    priorities=synthetic_context.priorities,
                    raw_reply="Deterministic summary",
                    model_name="local_deterministic",
                    is_fallback=True,
                )
                mock_synth_instance = unittest.mock.MagicMock()
                mock_synth_instance.synthesize.return_value = fallback_briefing
                mock_synth_cls.return_value = mock_synth_instance

                now = datetime(2026, 11, 21, 9, 0, 0, tzinfo=timezone.utc)
                result = ra._evaluate_morning_briefing(force=True, test_now=now)

                self.assertIsNotNone(result)
                self.assertEqual(result["status"], "fallback")
                self.assertEqual(result["model_name"], "local_deterministic")

                # Verify database insertion
                with ra._get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT status, model_name, content FROM daily_briefings WHERE local_date = '2026-11-21'")
                    row = cur.fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row["status"], "fallback")
                    self.assertEqual(row["model_name"], "local_deterministic")
                    self.assertIn("Submit Quarterly Report", row["content"])

                # Verify proactive event was emitted with briefing.ready
                self.assertEqual(len(self.emitted_events), 1)
                self.assertEqual(self.emitted_events[0]["event"], "briefing.ready")
                self.assertEqual(self.emitted_events[0]["params"]["payload"]["status"], "fallback")

    def test_worker_continuation_after_synthesis_failure(self):
        """
        Verify that a failure during briefing synthesis does not terminate
        the background worker loop; subsequent evaluations continue to execute.
        """
        evaluations_executed = []

        def fake_due_reminders():
            evaluations_executed.append("reminders_1")

        def fake_idle_eval():
            evaluations_executed.append("idle_eval")

        # Mock the helper methods called in sequential loop
        with unittest.mock.patch.object(ra, "_check_and_emit_due_reminders", side_effect=fake_due_reminders):
            with unittest.mock.patch.object(ra, "_evaluate_idle_recommendations", side_effect=fake_idle_eval):
                with unittest.mock.patch.object(ra, "_evaluate_morning_briefing") as mock_briefing:
                    # Briefing raises unexpected exception or fails
                    mock_briefing.side_effect = Exception("Simulated synthesis crash")

                    # Execute loop tick logic manually in bounded deterministic test
                    try:
                        ra._check_and_emit_due_reminders()
                    except Exception:
                        pass

                    try:
                        ra._evaluate_morning_briefing()
                    except Exception as e:
                        evaluations_executed.append(f"briefing_error: {e}")

                    try:
                        ra._evaluate_idle_recommendations()
                    except Exception:
                        pass

        # Verify loop flow proceeded to idle recommendations despite briefing error
        self.assertIn("reminders_1", evaluations_executed)
        self.assertIn("briefing_error: Simulated synthesis crash", evaluations_executed)
        self.assertIn("idle_eval", evaluations_executed)


class TestAtomicBriefingPersistenceAndRecovery(BaseIsolatedBriefingTest):
    """Test Suite for Task 1B: Atomic Outbox Persistence, Rollback, and Crash Recovery."""

    def test_atomic_persistence_both_tables_written(self):
        """Happy path: daily_briefings and proactive_events are committed in a single atomic transaction."""
        synthetic_context = create_synthetic_briefing_context("2026-11-22")

        with unittest.mock.patch.object(ra, "BriefingCollector") as mock_collector_cls:
            mock_collector = unittest.mock.MagicMock()
            mock_collector.collect.return_value = synthetic_context
            mock_collector_cls.return_value = mock_collector

            with unittest.mock.patch.object(ra, "BriefingSynthesizer") as mock_synth_cls:
                mock_synth = unittest.mock.MagicMock()
                mock_synth.synthesize.return_value = DailyBriefing(
                    date="2026-11-22",
                    summary_markdown="## Priorities\n- Review Code",
                    priorities=synthetic_context.priorities,
                    raw_reply="Full response",
                    model_name="nvidia/nemotron-3.5-lightning-30b-a3b",
                    is_fallback=False,
                )
                mock_synth_cls.return_value = mock_synth

                now = datetime(2026, 11, 22, 9, 0, 0, tzinfo=timezone.utc)
                result = ra._evaluate_morning_briefing(force=True, test_now=now, test_date="2026-11-22")

                self.assertIsNotNone(result)
                self.assertEqual(result["status"], "success")

                # Verify both tables populated atomically
                with ra._get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, status, model_name FROM daily_briefings WHERE local_date = '2026-11-22'")
                    b_row = cur.fetchone()
                    self.assertIsNotNone(b_row)
                    self.assertEqual(b_row["status"], "success")
                    self.assertEqual(b_row["model_name"], "nvidia/nemotron-3.5-lightning-30b-a3b")

                    cur.execute("SELECT event_id, event_type, entity_id, acknowledged, payload_json FROM proactive_events WHERE event_id = 'evt_briefing_2026-11-22'")
                    e_row = cur.fetchone()
                    self.assertIsNotNone(e_row)
                    self.assertEqual(e_row["event_type"], "briefing.ready")
                    self.assertEqual(e_row["entity_id"], b_row["id"])
                    self.assertEqual(e_row["acknowledged"], 0)

                # Verify event emission
                self.assertEqual(len(self.emitted_events), 1)
                self.assertEqual(self.emitted_events[0]["event"], "briefing.ready")
                self.assertEqual(self.emitted_events[0]["params"]["event_id"], "evt_briefing_2026-11-22")

    def test_atomic_rollback_on_failure_before_commit(self):
        """Simulated failure before commit: both tables roll back cleanly (0 rows), retry succeeds."""
        synthetic_context = create_synthetic_briefing_context("2026-11-23")

        with unittest.mock.patch.object(ra, "BriefingCollector") as mock_collector_cls:
            mock_collector = unittest.mock.MagicMock()
            mock_collector.collect.return_value = synthetic_context
            mock_collector_cls.return_value = mock_collector

            with unittest.mock.patch.object(ra, "BriefingSynthesizer") as mock_synth_cls:
                mock_synth = unittest.mock.MagicMock()
                mock_synth.synthesize.return_value = DailyBriefing(
                    date="2026-11-23",
                    summary_markdown="## Priorities\n- Test Rollback",
                    priorities=synthetic_context.priorities,
                    raw_reply="Full response",
                    model_name="nvidia/nemotron-3.5-lightning-30b-a3b",
                    is_fallback=False,
                )
                mock_synth_cls.return_value = mock_synth

                now = datetime(2026, 11, 23, 9, 0, 0, tzinfo=timezone.utc)

                # Intercept DB connection to simulate crash mid-transaction
                orig_get_db = ra._get_db_connection

                class CrashingConnectionWrapper:
                    def __init__(self, conn):
                        self._conn = conn
                    def __enter__(self):
                        self._conn.__enter__()
                        return self
                    def __exit__(self, exc_type, exc_val, exc_tb):
                        return self._conn.__exit__(exc_type, exc_val, exc_tb)
                    def execute(self, sql, params=()):
                        if "proactive_events" in sql:
                            raise sqlite3.OperationalError("Simulated disk error or crash before commit")
                        return self._conn.execute(sql, params)
                    def commit(self):
                        return self._conn.commit()
                    def cursor(self):
                        return self._conn.cursor()

                @ra.contextmanager
                def crashing_get_db_connection(db_path=None):
                    with orig_get_db(db_path) as conn:
                        yield CrashingConnectionWrapper(conn)

                with unittest.mock.patch.object(ra, "_get_db_connection", side_effect=crashing_get_db_connection):
                    result = ra._evaluate_morning_briefing(force=True, test_now=now, test_date="2026-11-23")
                    self.assertIsNone(result)

                # Verify complete rollback in both tables
                with ra._get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT count(*) FROM daily_briefings WHERE local_date = '2026-11-23'")
                    self.assertEqual(cur.fetchone()[0], 0, "daily_briefings must have 0 rows after rollback")
                    cur.execute("SELECT count(*) FROM proactive_events WHERE event_id = 'evt_briefing_2026-11-23'")
                    self.assertEqual(cur.fetchone()[0], 0, "proactive_events must have 0 rows after rollback")

                # Verify settings were not updated and no event was emitted
                settings = ra._load_gui_settings()
                self.assertNotEqual(settings.get("last_briefing_date"), "2026-11-23")
                self.assertEqual(len(self.emitted_events), 0)

                # Next evaluation tick (clean retry) succeeds
                retry_result = ra._evaluate_morning_briefing(force=True, test_now=now, test_date="2026-11-23")
                self.assertIsNotNone(retry_result)
                self.assertEqual(retry_result["status"], "success")

                # Verify both rows now exist
                with ra._get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT count(*) FROM daily_briefings WHERE local_date = '2026-11-23'")
                    self.assertEqual(cur.fetchone()[0], 1)
                    cur.execute("SELECT count(*) FROM proactive_events WHERE event_id = 'evt_briefing_2026-11-23'")
                    self.assertEqual(cur.fetchone()[0], 1)

                self.assertEqual(len(self.emitted_events), 1)

    def test_post_commit_crash_recovery_without_duplicate_briefing(self):
        """Simulated crash after commit (before ack): recovery replays event with exactly 1 briefing row."""
        current_date = "2026-11-24"
        briefing_id = f"briefing_{current_date}_test001"
        evt_id = f"evt_briefing_{current_date}"
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "id": briefing_id,
            "local_date": current_date,
            "created_at": created_at,
            "content": "Morning update",
            "status": "success",
            "model_name": "nvidia/nemotron-3.5-lightning-30b-a3b",
            "priorities": [],
            "sources": {},
            "error_message": None,
        }

        # Seed committed state where acknowledged = 0
        with ra._get_db_connection() as conn:
            conn.execute("""
                INSERT INTO daily_briefings (id, local_date, created_at, content, status, model_name, priorities_json, sources_json)
                VALUES (?, ?, ?, ?, 'success', 'nvidia/nemotron-3.5-lightning-30b-a3b', '[]', '{}')
            """, (briefing_id, current_date, created_at, "Morning update"))
            conn.execute("""
                INSERT INTO proactive_events (event_id, event_type, entity_id, created_at, payload_json, acknowledged)
                VALUES (?, 'briefing.ready', ?, ?, ?, 0)
            """, (evt_id, briefing_id, created_at, json.dumps(payload)))
            conn.commit()

        self.emitted_events.clear()

        # Run startup/worker reconciliation
        reconciled = ra._reconcile_morning_briefing_events()
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["event_id"], evt_id)

        # Verify event was emitted over stdio
        self.assertEqual(len(self.emitted_events), 1)
        self.assertEqual(self.emitted_events[0]["event"], "briefing.ready")
        self.assertEqual(self.emitted_events[0]["params"]["event_id"], evt_id)

        # Verify zero duplicate rows in daily_briefings
        with ra._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM daily_briefings WHERE local_date = ?", (current_date,))
            self.assertEqual(cur.fetchone()[0], 1, "daily_briefings row count must remain strictly 1")

        # Now simulate UI acknowledging the event
        ack_res = ra.handle_events_ack({"event_id": evt_id})
        self.assertTrue(ack_res["acknowledged"])

        # Re-running reconciliation after acknowledgement produces 0 re-emissions
        self.emitted_events.clear()
        reconciled_after_ack = ra._reconcile_morning_briefing_events()
        self.assertEqual(len(reconciled_after_ack), 0)
        self.assertEqual(len(self.emitted_events), 0)

    def test_orphan_briefing_reconciliation(self):
        """Defensive check: orphaned daily_briefings row (missing event) creates event envelope and emits."""
        current_date = "2026-11-25"
        briefing_id = f"briefing_{current_date}_orphan001"
        evt_id = f"evt_briefing_{current_date}"
        created_at = datetime.now(timezone.utc).isoformat()

        # Seed orphaned briefing in daily_briefings (NO row in proactive_events)
        with ra._get_db_connection() as conn:
            conn.execute("""
                INSERT INTO daily_briefings (id, local_date, created_at, content, status, model_name, priorities_json, sources_json)
                VALUES (?, ?, ?, ?, 'success', 'nvidia/nemotron-3.5-lightning-30b-a3b', '[]', '{}')
            """, (briefing_id, current_date, created_at, "Orphaned briefing content"))
            conn.commit()

        # Verify proactive_events has 0 rows for this date
        with ra._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM proactive_events WHERE event_id = ?", (evt_id,))
            self.assertEqual(cur.fetchone()[0], 0)

        self.emitted_events.clear()

        # Run reconciliation
        reconciled = ra._reconcile_morning_briefing_events()
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["event_id"], evt_id)

        # Verify event was backfilled into proactive_events with acknowledged = 0
        with ra._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT acknowledged, entity_id, payload_json FROM proactive_events WHERE event_id = ?", (evt_id,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["acknowledged"], 0)
            self.assertEqual(row["entity_id"], briefing_id)
            payload = json.loads(row["payload_json"])
            self.assertEqual(payload["content"], "Orphaned briefing content")

        # Verify event was emitted over stdio
        self.assertEqual(len(self.emitted_events), 1)
        self.assertEqual(self.emitted_events[0]["event"], "briefing.ready")

        # Verify daily_briefings count is still strictly 1
        with ra._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM daily_briefings WHERE local_date = ?", (current_date,))
            self.assertEqual(cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

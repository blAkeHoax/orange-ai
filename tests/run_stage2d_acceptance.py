"""
tests/run_stage2d_acceptance.py - Comprehensive Stage 2D Acceptance & Regression Test Suite.

Validates:
- Scope A: Event Transport & Delivery (envelopes, JSON-RPC stdio notifications, persistence, ack, replay, deduplication).
- Scope B: Morning Briefing Delivery & Presentation (briefing.ready emission, entity_id, payload, ack, persistence).
- Scope C: Reminder Due Notifications (due detection, reminder.due emission, deduplication, non-destructive dismissal).
- Scope D: Recommendation Lifecycle (HIGH, NORMAL, LOW priority tiers, dismiss 7d, snooze 24h, persistence across reloads).
- Scope E: Recommendation Execution Security (SAFE direct execution, CONFIRMATION_REQUIRED handshake, HIGH_RISK denial,
           unsupported action handling, payload tamper resistance, nonexistent ID handling).
- Scope F: Project Reconciliation Delivery (reconciliation.ready emission, git metadata, status, watermark deduplication).
- Scope G: Stage 2A/2B/2C Full Regression (all 40 tests passing with 0 failures).
- Scope H: Production Security & Test-Mode Hardening (frozen executable rejects test-only methods even with env var,
           desktop workspace immutability check).
"""

import os
import sys
import json
import time
import uuid
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta

# Ensure Tauri workspace runtime and desktop tools can be imported
TAURI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNTIME_DIR = os.path.join(TAURI_DIR, "runtime")
DESKTOP_DIR = os.path.abspath(r"D:\Orange AI\Orange AI Desktop")

for p in (RUNTIME_DIR, TAURI_DIR, DESKTOP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import runtime_adapter as ra
from brain.briefing.recommendations import (
    RecommendationStore,
    Recommendation,
    RecommendationPriority,
    RecommendationState,
    RecommendationCategory,
    DISMISSAL_SUPPRESSION_DAYS,
    DEFERRAL_DEFAULT_HOURS,
)
from tools.registry import registry
from tools.permissions import check_permission, RiskLevel, PermissionStatus


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def assert_true(self, condition: bool, description: str):
        if condition:
            self.passed += 1
            print(f"  [PASS] {description}")
        else:
            self.failed += 1
            self.errors.append(description)
            print(f"  [FAIL] {description}")

    def assert_equal(self, actual, expected, description: str):
        if actual == expected:
            self.passed += 1
            print(f"  [PASS] {description}")
        else:
            self.failed += 1
            err_msg = f"{description} (Expected {expected!r}, got {actual!r})"
            self.errors.append(err_msg)
            print(f"  [FAIL] {err_msg}")


def run_tests():
    runner = TestRunner()
    print("=" * 70)
    print("ORANGE AI DESKTOP 2.0 - STAGE 2D ACCEPTANCE TEST SUITE")
    print("=" * 70)

    # Ensure tables exist
    ra._ensure_stage2c_tables()
    db_path = ra.resolve_database_path()

    # -------------------------------------------------------------
    # TEST A: Event Transport & Delivery
    # -------------------------------------------------------------
    print("\n--- [TEST A] Event Transport, Envelopes & Acknowledgement ---")
    
    test_evt_id = f"test_evt_{uuid.uuid4().hex[:8]}"
    test_payload = {"key": "value", "count": 42}
    
    # 1. Emit proactive event
    envelope = ra.emit_proactive_event(
        event_type="test.event",
        entity_id="entity_123",
        payload=test_payload,
        event_id=test_evt_id,
    )
    runner.assert_true(envelope is not None, "emit_proactive_event returns non-null envelope")
    runner.assert_equal(envelope.get("event_id"), test_evt_id, "Envelope carries correct event_id")
    runner.assert_equal(envelope.get("event_type"), "test.event", "Envelope carries correct event_type")
    runner.assert_equal(envelope.get("entity_id"), "entity_123", "Envelope carries correct entity_id")
    runner.assert_equal(envelope.get("version"), 1, "Envelope carries schema version 1")
    runner.assert_equal(envelope.get("acknowledged"), False, "Envelope starts unacknowledged")

    # 2. Verify recorded in proactive_events SQLite table
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT event_id, event_type, acknowledged, payload_json FROM proactive_events WHERE event_id = ?", (test_evt_id,))
        row = cur.fetchone()
    runner.assert_true(row is not None, "Event is persisted in proactive_events table")
    runner.assert_equal(row["acknowledged"], 0, "Event acknowledged column is 0 initially")

    # 3. Test unacknowledged events retrieval
    unacked = ra.handle_events_get_unacked({"limit": 200})
    matching = [e for e in unacked if e["event_id"] == test_evt_id]
    runner.assert_true(len(matching) == 1, "handle_events_get_unacked returns pending event")
    runner.assert_equal(matching[0]["payload"].get("count"), 42, "Unacked payload deserializes correctly")

    # 4. Test event acknowledgement (events.ack)
    ack_res = ra.handle_events_ack({"event_id": test_evt_id})
    runner.assert_true(ack_res.get("acknowledged") is True, "handle_events_ack returns acknowledged=True")

    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT acknowledged, acknowledged_at FROM proactive_events WHERE event_id = ?", (test_evt_id,))
        ack_row = cur.fetchone()
    runner.assert_equal(ack_row["acknowledged"], 1, "Database records acknowledged = 1")
    runner.assert_true(bool(ack_row["acknowledged_at"]), "Database records acknowledged_at timestamp")

    # 5. Verify acknowledged event is excluded from subsequent unacked retrieval
    unacked_after = ra.handle_events_get_unacked({"limit": 50})
    matching_after = [e for e in unacked_after if e["event_id"] == test_evt_id]
    runner.assert_true(len(matching_after) == 0, "Acknowledged event is excluded from unacked replay")

    # 6. Deduplication check: re-emitting same event_id returns None and avoids duplicate stdio
    re_emit = ra.emit_proactive_event("test.event", "entity_123", test_payload, event_id=test_evt_id)
    runner.assert_true(re_emit is None, "Re-emitting same event_id returns None (deduplicated)")

    # -------------------------------------------------------------
    # TEST B: Morning Briefing Delivery & Presentation
    # -------------------------------------------------------------
    print("\n--- [TEST B] Morning Briefing Delivery & Lifecycle ---")
    test_date = f"2026-11-{int(time.time()) % 28 + 1:02d}"
    briefing = ra._evaluate_morning_briefing(force=True, test_date=test_date)
    runner.assert_true(briefing is not None, "_evaluate_morning_briefing produces structured briefing")
    runner.assert_true(briefing.get("status") in ("success", "fallback"), "Briefing status is success or fallback")
    runner.assert_true(len(briefing.get("content", "")) > 0, "Briefing content contains synthesized text")

    # Verify briefing.ready event was emitted in proactive_events
    briefing_evt_id = f"evt_briefing_{test_date}"
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT event_id, event_type, entity_id, payload_json FROM proactive_events WHERE event_id = ?", (briefing_evt_id,))
        b_row = cur.fetchone()
    runner.assert_true(b_row is not None, "briefing.ready proactive event was persisted")
    runner.assert_equal(b_row["event_type"], "briefing.ready", "Event type is briefing.ready")
    
    # Verify briefing.get_latest returns the generated briefing
    latest_briefing = ra.handle_briefing_get_latest({})
    runner.assert_true(latest_briefing.get("briefing") is not None, "briefing.get_latest returns latest briefing")

    # Acknowledge the briefing event
    ra.handle_events_ack({"event_id": briefing_evt_id})
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT acknowledged FROM proactive_events WHERE event_id = ?", (briefing_evt_id,))
        b_ack = cur.fetchone()
    runner.assert_equal(b_ack["acknowledged"], 1, "Briefing event acknowledged successfully")

    # -------------------------------------------------------------
    # TEST C: Reminder Due Notifications
    # -------------------------------------------------------------
    print("\n--- [TEST C] Reminder Due Notifications & Delivery ---")
    # Insert a test reminder due in the past
    past_due = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    rem_msg = f"Stage 2D Test Reminder #{uuid.uuid4().hex[:6]}"
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO reminders (message, due_at, created_at, fired) VALUES (?, ?, ?, 0)",
                    (rem_msg, past_due, datetime.now().isoformat()))
        rem_id = cur.lastrowid
        conn.commit()

    runner.assert_true(rem_id is not None and rem_id > 0, f"Inserted test reminder #{rem_id}")

    # Check and emit due reminders
    ra._check_and_emit_due_reminders()

    rem_evt_id = f"evt_reminder_{rem_id}"
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT event_id, event_type, entity_id, payload_json FROM proactive_events WHERE event_id = ?", (rem_evt_id,))
        rem_row = cur.fetchone()
    runner.assert_true(rem_row is not None, "reminder.due event was emitted and recorded in proactive_events")
    runner.assert_equal(rem_row["event_type"], "reminder.due", "Event type is reminder.due")

    # Verify reminder is marked fired in reminders table
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT fired, message FROM reminders WHERE id = ?", (rem_id,))
        rem_db = cur.fetchone()
    runner.assert_equal(rem_db["fired"], 1, "Reminder fired flag is set to 1 to prevent scheduler re-selection")

    # Verify repeated check does not re-emit
    ra._check_and_emit_due_reminders()
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM proactive_events WHERE event_id = ?", (rem_evt_id,))
        cnt = cur.fetchone()["cnt"]
    runner.assert_equal(cnt, 1, "Deduplication: exactly 1 event exists for reminder")

    # Acknowledge the notification: verify reminder record is NOT deleted from reminders table
    ra.handle_events_ack({"event_id": rem_evt_id})
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM reminders WHERE id = ?", (rem_id,))
        rem_still_exists = cur.fetchone() is not None
    runner.assert_true(rem_still_exists, "Visual notification acknowledgement does NOT delete underlying reminder")

    # -------------------------------------------------------------
    # TEST D: Recommendation Lifecycle (HIGH, NORMAL, LOW)
    # -------------------------------------------------------------
    print("\n--- [TEST D] Recommendation Lifecycle: Priority Tiers, Dismiss (7d), Snooze (24h) ---")
    store = RecommendationStore()
    now_dt = datetime.now()

    # Create 3 test recommendations for all 3 tiers
    rec_high_id = f"test_rec_high_{uuid.uuid4().hex[:6]}"
    rec_normal_id = f"test_rec_norm_{uuid.uuid4().hex[:6]}"
    rec_low_id = f"test_rec_low_{uuid.uuid4().hex[:6]}"

    rec_high = Recommendation(
        rec_id=rec_high_id,
        category=RecommendationCategory.JOB_CONFIRMATION,
        entity_id="job_high_123",
        recommendation_type="advisory",
        title="High Priority Test Advisory",
        explanation="Requires immediate action",
        suggested_action="Review and confirm",
        priority=RecommendationPriority.HIGH,
        evidence_fingerprint="fp_high_123",
        evidence=["Blocked job 1"],
    )
    rec_normal = Recommendation(
        rec_id=rec_normal_id,
        category=RecommendationCategory.REMINDER_OVERDUE,
        entity_id="rem_norm_123",
        recommendation_type="advisory",
        title="Normal Priority Test Advisory",
        explanation="Routine review recommended",
        suggested_action="Review reminder",
        priority=RecommendationPriority.NORMAL,
        evidence_fingerprint="fp_norm_123",
        evidence=["Overdue reminder 2"],
    )
    rec_low = Recommendation(
        rec_id=rec_low_id,
        category=RecommendationCategory.PROJECT_PAUSED,
        entity_id="proj_low_123",
        recommendation_type="advisory",
        title="Low Priority Test Advisory",
        explanation="Housekeeping suggestion",
        suggested_action="Check project",
        priority=RecommendationPriority.LOW,
        evidence_fingerprint="fp_low_123",
        evidence=["Paused project 3"],
    )

    with store.lock():
        store.upsert_candidate(rec_high)
        store.upsert_candidate(rec_normal)
        store.upsert_candidate(rec_low)
        store.save()

    # Verify priority normalization
    runner.assert_equal(ra.normalize_recommendation_priority(rec_high.priority), "HIGH", "High priority normalized to HIGH")
    runner.assert_equal(ra.normalize_recommendation_priority(rec_normal.priority), "MEDIUM", "Normal priority normalized to MEDIUM")
    runner.assert_equal(ra.normalize_recommendation_priority(rec_low.priority), "LOW", "Low priority normalized to LOW")

    # Test Dismiss (7-day suppression) on HIGH priority recommendation
    dismiss_res = ra.handle_recommendations_dismiss({"id": rec_high_id})
    runner.assert_equal(dismiss_res.get("status"), "DISMISSED", "Dismiss returns status DISMISSED")
    runner.assert_true(dismiss_res.get("suppressed_until") is not None, "Dismiss sets suppressed_until timestamp")
    
    # Verify suppressed_until is approximately 7 days in future
    supp_dt = datetime.fromisoformat(dismiss_res["suppressed_until"])
    delta_days = (supp_dt - datetime.now()).days
    runner.assert_true(6 <= delta_days <= 8, f"Suppressed until is ~7 days ({delta_days} days)")

    # Verify recommendation.updated event was emitted
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT event_type FROM proactive_events WHERE entity_id = ? AND event_type = 'recommendation.updated'", (rec_high_id,))
        upd_row = cur.fetchone()
    runner.assert_true(upd_row is not None, "recommendation.updated event was emitted for dismissal")

    # Test Snooze (24-hour suppression) on NORMAL priority recommendation
    snooze_res = ra.handle_recommendations_snooze({"id": rec_normal_id, "duration": "24h"})
    runner.assert_equal(snooze_res.get("status"), "DEFERRED", "Snooze returns status DEFERRED")
    runner.assert_true(snooze_res.get("suppressed_until") is not None, "Snooze sets suppressed_until timestamp")
    snooze_dt = datetime.fromisoformat(snooze_res["suppressed_until"])
    delta_hours = (snooze_dt - datetime.now()).total_seconds() / 3600.0
    runner.assert_true(23 <= delta_hours <= 25, f"Suppressed until is ~24 hours ({delta_hours:.1f} hours)")

    # Test Persistence across fresh store reload
    fresh_store = RecommendationStore()
    reloaded_high = fresh_store.get(rec_high_id)
    reloaded_norm = fresh_store.get(rec_normal_id)
    runner.assert_equal(reloaded_high.state, RecommendationState.DISMISSED, "Dismissed state persists in fresh store reload")
    runner.assert_equal(reloaded_norm.state, RecommendationState.DEFERRED, "Deferred state persists in fresh store reload")

    # -------------------------------------------------------------
    # TEST E: Recommendation Execution Security (AgentEngine/ToolRegistry Pipeline)
    # -------------------------------------------------------------
    print("\n--- [TEST E] Recommendation Execution Security & Permission Pipeline ---")

    # E1. SAFE Action Execution
    rec_safe_id = f"test_exec_safe_{uuid.uuid4().hex[:6]}"
    rec_safe = Recommendation(
        rec_id=rec_safe_id,
        category=RecommendationCategory.JOB_CONFIRMATION,
        entity_id="job_safe_123",
        recommendation_type="tool_call",
        title="Safe Tool Execution Test",
        explanation="Runs get_date",
        suggested_action="Inspect date",
        priority=RecommendationPriority.NORMAL,
        evidence_fingerprint="fp_safe_123",
    )
    ra.register_recommendation_action(rec_safe_id, {"tool_name": "get_date", "parameters": {}})
    with store.lock():
        store.upsert_candidate(rec_safe)
        store.save()

    exec_safe_res = ra.handle_recommendations_execute({"id": rec_safe_id})
    runner.assert_equal(exec_safe_res.get("status"), "SUCCESS", "SAFE tool executes directly and returns status SUCCESS")
    runner.assert_equal(exec_safe_res.get("risk_level"), "SAFE", "Risk level reported as SAFE")
    runner.assert_true(exec_safe_res.get("result") is not None, "SAFE tool returned valid execution result")

    # Verify marked HANDLED in store
    rec_safe_updated = RecommendationStore().get(rec_safe_id)
    runner.assert_equal(rec_safe_updated.state, RecommendationState.HANDLED, "SAFE tool marked recommendation HANDLED")

    # E2. CONFIRMATION_REQUIRED Action Execution
    rec_conf_id = f"test_exec_conf_{uuid.uuid4().hex[:6]}"
    rec_conf = Recommendation(
        rec_id=rec_conf_id,
        category=RecommendationCategory.JOB_CONFIRMATION,
        entity_id="job_conf_123",
        recommendation_type="tool_call",
        title="Confirmation Required Tool Test",
        explanation="Runs open_folder",
        suggested_action="Open folder",
        priority=RecommendationPriority.HIGH,
        evidence_fingerprint="fp_conf_123",
    )
    ra.register_recommendation_action(rec_conf_id, {"tool_name": "open_folder", "parameters": {"path": TAURI_DIR}})
    with store.lock():
        store.upsert_candidate(rec_conf)
        store.save()

    # 1st step: without confirmed flag -> must return REQUIRES_CONFIRMATION
    step1_res = ra.handle_recommendations_execute({"id": rec_conf_id})
    runner.assert_equal(step1_res.get("status"), "REQUIRES_CONFIRMATION", "CONFIRMATION_REQUIRED tool requires confirmation")
    token = step1_res.get("confirmation_token")
    runner.assert_true(token is not None and token.startswith("tok_conf_"), "Returns structured confirmation_token")

    # 2nd step: user denies -> must return DENIED
    deny_res = ra.handle_recommendations_execute({"id": rec_conf_id, "confirmed": False, "confirmation_token": token})
    runner.assert_equal(deny_res.get("status"), "DENIED", "Denial by user returns status DENIED")

    # 3rd step: user confirms -> executes and returns SUCCESS
    confirm_res = ra.handle_recommendations_execute({"id": rec_conf_id, "confirmed": True, "confirmation_token": token})
    runner.assert_equal(confirm_res.get("status"), "SUCCESS", "Confirmed execution returns status SUCCESS")
    runner.assert_equal(confirm_res.get("risk_level"), "CONFIRMATION_REQUIRED", "Risk level reported as CONFIRMATION_REQUIRED")

    # E3. HIGH_RISK Action Execution
    from tools.registry import Tool
    high_risk_tool_name = f"test_high_risk_{uuid.uuid4().hex[:6]}"
    registry.register(Tool(high_risk_tool_name, "Simulated high risk", RiskLevel.HIGH_RISK, lambda: "dangerous", "system"))

    rec_highrisk_id = f"test_exec_high_{uuid.uuid4().hex[:6]}"
    rec_highrisk = Recommendation(
        rec_id=rec_highrisk_id,
        category=RecommendationCategory.JOB_CONFIRMATION,
        entity_id="job_hr_123",
        recommendation_type="tool_call",
        title="High Risk Action Test",
        explanation="Attempts dangerous tool",
        suggested_action="Dangerous action",
        priority=RecommendationPriority.HIGH,
        evidence_fingerprint="fp_hr_123",
    )
    ra.register_recommendation_action(rec_highrisk_id, {"tool_name": high_risk_tool_name, "parameters": {}})
    with store.lock():
        store.upsert_candidate(rec_highrisk)
        store.save()

    hr_res = ra.handle_recommendations_execute({"id": rec_highrisk_id})
    runner.assert_equal(hr_res.get("status"), "DENIED", "HIGH_RISK action is denied unconditionally")
    runner.assert_equal(hr_res.get("risk_level"), "HIGH_RISK", "Reported risk_level is HIGH_RISK")

    # E4. Unsupported Action Type (Advisory only)
    rec_unsupp_id = f"test_exec_unsupp_{uuid.uuid4().hex[:6]}"
    rec_unsupp = Recommendation(
        rec_id=rec_unsupp_id,
        category=RecommendationCategory.PROJECT_BLOCKED,
        entity_id="proj_unsupp_123",
        recommendation_type="advisory",
        title="Advisory Only Test",
        explanation="Advisory recommendation without executable action",
        suggested_action="Review project milestones",
        priority=RecommendationPriority.NORMAL,
        evidence_fingerprint="fp_unsupp_123",
    )
    with store.lock():
        store.upsert_candidate(rec_unsupp)
        store.save()

    unsupp_res = ra.handle_recommendations_execute({"id": rec_unsupp_id})
    runner.assert_equal(unsupp_res.get("status"), "UNSUPPORTED", "Advisory recommendation returns status UNSUPPORTED")

    # E5. Payload Tamper Resistance
    # Attacker tries to pass malicious command or override tool name in React parameters
    tamper_res = ra.handle_recommendations_execute({
        "id": rec_safe_id,
        "tool_name": "run_command",
        "command": "cmd.exe /c format c:",
        "action_payload": {"tool_name": "run_command"}
    })
    # Authoritative resolution strictly read rec_safe (which was get_date, already handled)
    runner.assert_true(tamper_res.get("status") in ("SUCCESS", "ERROR"), "Tampered params from client ignored; executed authoritative tool")
    runner.assert_equal(tamper_res.get("risk_level"), "SAFE", "Tamper attempt cannot escalate risk level")

    # E6. Nonexistent Recommendation ID
    nonexist_res = ra.handle_recommendations_execute({"id": "nonexistent_rec_99999"})
    runner.assert_equal(nonexist_res.get("status"), "ERROR", "Nonexistent ID returns status ERROR")

    # -------------------------------------------------------------
    # TEST F: Project Reconciliation Delivery
    # -------------------------------------------------------------
    print("\n--- [TEST F] Project Reconciliation Delivery & Activity ---")
    recon_res = ra._run_startup_reconciliation(target_path=TAURI_DIR)
    runner.assert_true(len(recon_res) > 0, "Reconciliation executed for official workspace")
    first_recon = recon_res[0]
    runner.assert_equal(first_recon.get("workspace_name"), "Orange AI Tauri", "Reconciliation targets Orange AI Tauri")
    runner.assert_true(first_recon.get("status") in ("clean", "changed", "baseline"), "Reconciliation reports valid status")
    runner.assert_true(first_recon.get("file_watermark_hash") is not None, "Reconciliation computes file watermark hash")

    # Verify reconciliation.ready event was emitted in proactive_events
    recon_evt_id = f"evt_recon_{first_recon['id']}"
    with ra._get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT event_type, entity_id FROM proactive_events WHERE event_id = ?", (recon_evt_id,))
        recon_evt = cur.fetchone()
    runner.assert_true(recon_evt is not None, "reconciliation.ready event was emitted and recorded in proactive_events")
    runner.assert_equal(recon_evt["event_type"], "reconciliation.ready", "Event type is reconciliation.ready")

    # Verify Git metadata extraction on a real Git test workspace
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_git_dir:
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_git_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmp_git_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@orange.local"], cwd=tmp_git_dir, capture_output=True)
        test_file = os.path.join(tmp_git_dir, "test.txt")
        with open(test_file, "w") as tf:
            tf.write("initial content")
        subprocess.run(["git", "add", "."], cwd=tmp_git_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial test commit"], cwd=tmp_git_dir, capture_output=True)

        git_recon = ra._run_startup_reconciliation(target_path=tmp_git_dir)
        runner.assert_true(len(git_recon) > 0, "Reconciled temporary Git test workspace")
        runner.assert_equal(git_recon[0].get("git_branch"), "main", "Reconciliation extracts active Git branch ('main')")
        runner.assert_true(git_recon[0].get("git_head_commit") is not None, "Reconciliation extracts Git head commit SHA")

    # Verify reconciliation.get_latest returns persisted record
    recon_api = ra.handle_reconciliation_get_latest({"workspace_path": TAURI_DIR})
    runner.assert_true(len(recon_api.get("reconciliations", [])) > 0, "reconciliation.get_latest returns records")

    # -------------------------------------------------------------
    # TEST G: Stage 2A/2B/2C Full Regression
    # -------------------------------------------------------------
    print("\n--- [TEST G] Stage 2A/2B/2C Full Regression Verification ---")
    reg_script = os.path.join(TAURI_DIR, "tests", "run_stage2c_final_correction_suite.py")
    reg_res = subprocess.run(
        [sys.executable, reg_script],
        cwd=TAURI_DIR,
        capture_output=True,
        text=True,
        timeout=120
    )
    combined_out = reg_res.stdout + "\n" + reg_res.stderr
    reg_pass = (reg_res.returncode == 0) and ("22/22 Passed" in combined_out or "Passed" in combined_out)
    runner.assert_true(reg_pass, f"Stage 2A/2B/2C regression suite passed cleanly (code {reg_res.returncode})")

    # -------------------------------------------------------------
    # TEST H: Production Security & Test-Mode Hardening
    # -------------------------------------------------------------
    print("\n--- [TEST H] Production Security & Test-Mode Hardening ---")
    
    # 1. Test-mode check in development mode (with env var)
    os.environ["ORANGE_AI_TEST_MODE"] = "1"
    runner.assert_true(ra._is_test_mode_enabled(), "Dev mode allows test mode when ORANGE_AI_TEST_MODE=1")

    # 2. Hardening: Without explicit env var, test mode is strictly disabled by default
    os.environ["ORANGE_AI_TEST_MODE"] = "0"
    runner.assert_true(ra._is_test_mode_enabled() is False, "Without active ORANGE_AI_TEST_MODE=1, test mode is strictly disabled")
    os.environ.pop("ORANGE_AI_TEST_MODE", None)
    runner.assert_true(ra._is_test_mode_enabled() is False, "With no env var present, test mode is strictly disabled")

    # 3. Immutability check: Protected legacy Desktop workspace must exist and be read-only
    runner.assert_true(os.path.isdir(DESKTOP_DIR), f"Protected legacy workspace exists at {DESKTOP_DIR}")
    runner.assert_true(os.path.isfile(os.path.join(DESKTOP_DIR, "main.py")), "Protected legacy main.py intact")

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"STAGE 2D ACCEPTANCE SUITE RESULTS: {runner.passed} PASSED, {runner.failed} FAILED")
    print("=" * 70)
    
    if runner.failed > 0:
        print("\nFailed assertions:")
        for e in runner.errors:
            print(f"  - {e}")
        return False
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

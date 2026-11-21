"""
verify_corrections_internal.py - Quick validation of Stage 2C corrections in Python runtime.
"""
import os
import sys
import json

TAURI_ROOT = r"D:\Orange AI\Orange AI Tauri"
DESKTOP_ROOT = r"D:\Orange AI\Orange AI Desktop"
RUNTIME_DIR = os.path.join(TAURI_ROOT, "runtime")
os.environ["ORANGE_AI_USER_DATA_DIR"] = r"C:\Users\User\AppData\Local\Orange AI"

# 1. Ensure test mode is NOT set initially
if "ORANGE_AI_TEST_MODE" in os.environ:
    del os.environ["ORANGE_AI_TEST_MODE"]

if DESKTOP_ROOT not in sys.path:
    sys.path.insert(0, DESKTOP_ROOT)
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

import runtime_adapter as ra

print("==================================================================")
print("--- TEST 1: PRODUCTION DISPATCHER GUARDS (TEST MODE DISABLED) ---")
print("==================================================================")
print("Is test mode enabled:", ra._is_test_mode_enabled())
assert not ra._is_test_mode_enabled(), "Test mode must be disabled by default!"

responses = {}
def mock_send_response(req_id, result):
    responses[req_id] = {"result": result}
def mock_send_error(req_id, code, message):
    responses[req_id] = {"error": {"code": code, "message": message}}

ra.send_response = mock_send_response
ra.send_error = mock_send_error

test_methods = [
    "stage2c.trigger_briefing",
    "stage2c.trigger_idle_eval",
    "stage2c.set_idle_threshold",
    "stage2c.trigger_reconciliation",
]

for m in test_methods:
    ra.dispatch_request(f"test-{m}", m, {})
    resp = responses.get(f"test-{m}")
    print(f"Production call {m}: {resp}")
    assert resp is not None, f"No response for {m}"
    assert "error" in resp, f"Expected error for {m}, got {resp}"
    assert resp["error"]["code"] == -32601, f"Expected code -32601 for {m}, got {resp['error']['code']}"
    assert "not found" in resp["error"]["message"].lower()

print("\n--- TEST 2: SETTINGS.UPDATE REJECTS TEST MODE ---")
ra.dispatch_request("test-settings-update", "settings.update", {"settings": {"test_mode": True}})
resp = responses.get("test-settings-update")
print("settings.update with test_mode payload:", resp)
assert resp is not None and "result" in resp
assert resp["result"]["success"] is False
assert "test_mode" in resp["result"]["error"]
assert not ra._is_test_mode_enabled()

print("\n--- TEST 3: PRODUCTION READ METHODS AVAILABLE ---")
prod_methods = [
    "briefing.get_latest",
    "briefing.list",
    "recommendations.get_active",
    "reconciliation.get_latest",
]
for m in prod_methods:
    ra.dispatch_request(f"prod-{m}", m, {})
    resp = responses.get(f"prod-{m}")
    has_res = resp is not None and "result" in resp
    print(f"Production method {m}: result present = {has_res}")
    assert has_res, f"Expected valid result for {m}"

print("\n--- TEST 4: RECOMMENDATION PRIORITY CONTRACT ---")
# Migrate file if needed
migrated = ra._migrate_recommendations_file()
print(f"Migrated legacy records on disk: {migrated}")

ra.dispatch_request("get-recs", "recommendations.get_active", {})
resp = responses.get("get-recs")
active_recs = resp["result"].get("recommendations", [])
print(f"Total active recommendations retrieved: {len(active_recs)}")
valid_priorities = {"HIGH", "MEDIUM", "LOW"}
for r in active_recs:
    prio = r.get("priority")
    print(f"  Rec id={r['id'][:25]} priority={prio}")
    assert prio in valid_priorities, f"Priority '{prio}' not in {valid_priorities}"

print("\n--- TEST 5: TEST MODE ACTIVATION VIA ENVIRONMENT ---")
os.environ["ORANGE_AI_TEST_MODE"] = "1"
print("Is test mode enabled with ORANGE_AI_TEST_MODE=1:", ra._is_test_mode_enabled())
assert ra._is_test_mode_enabled(), "Test mode should now be enabled"

ra.dispatch_request("test-thresh", "stage2c.set_idle_threshold", {"seconds": 450.0})
resp = responses.get("test-thresh")
print("stage2c.set_idle_threshold in test mode:", resp)
assert resp is not None and "result" in resp
assert resp["result"]["success"] is True
assert resp["result"]["idle_threshold_seconds"] == 450.0

print("\n==================================================================")
print("ALL INTERNAL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
print("==================================================================")

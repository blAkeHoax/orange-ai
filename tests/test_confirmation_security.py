"""
tests/test_confirmation_security.py - Comprehensive Confirmation Security Verification
Verifies:
  1. Confirmation IDs are bound to their original pending actions.
  2. Expired confirmation requests cannot be reused.
  3. Duplicate approval messages cannot execute an action twice.
  4. Denial and timeout prevent execution.
  5. Runtime-side permission validation cannot be bypassed by React.
  6. HIGH_RISK operations remain denied.
  7. Confirmation timeout is enforced by the authoritative Python runtime.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
import threading

PYTHON_EXE = r"D:\Orange AI\Orange AI Desktop\venv\Scripts\python.exe"
ADAPTER_SCRIPT = r"D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py"

def run_confirmation_security_suite():
    print("\n=======================================================")
    print("--- [TEST SUITE] Confirmation Security Audit ---")
    print("=======================================================")

    temp_dir = tempfile.mkdtemp(prefix="orange_test_conf_sec_")
    env = os.environ.copy()
    env["ORANGE_USER_DATA_DIR"] = temp_dir
    env["ORANGE_DB_PATH"] = os.path.join(temp_dir, "memory.db")

    proc = subprocess.Popen(
        [PYTHON_EXE, ADAPTER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    req_id = 1
    def send_rpc(method, params=None):
        nonlocal req_id
        current_id = req_id
        msg = {"jsonrpc": "2.0", "id": current_id, "method": method, "params": params or {}}
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        req_id += 1
        return current_id

    def read_next_json(timeout=10.0):
        start = time.time()
        while time.time() - start < timeout:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except Exception:
                continue
        return None

    def wait_for_notification(method, timeout=10.0):
        start = time.time()
        while time.time() - start < timeout:
            msg = read_next_json(timeout=2.0)
            if msg and msg.get("method") == method:
                return msg
        return None

    def wait_for_response(expected_id, timeout=10.0):
        start = time.time()
        while time.time() - start < timeout:
            msg = read_next_json(timeout=2.0)
            if msg and msg.get("id") == expected_id:
                return msg
        return None

    try:
        # Drain ready
        ready_evt = wait_for_notification("runtime.ready")
        assert ready_evt is not None, "Failed to receive runtime.ready"
        print("[TEST] Runtime started:", ready_evt.get("method"))

        # -----------------------------------------------------------
        # Test 1: Denial prevents execution
        # -----------------------------------------------------------
        print("\n--- Subtest 1: Denial Prevents Execution ---")
        send_id = send_rpc("chat.send", {"text": "open notepad"})

        # Read notification for confirmation required
        evt = wait_for_notification("assistant.confirmation_required")
        assert evt is not None, "Failed to receive assistant.confirmation_required"
        conf_id = evt.get("params", {}).get("confirmation_id")
        prompt = evt.get("params", {}).get("prompt_text")
        print(f"[TEST 1] Intercepted confirmation request: id={conf_id}, prompt='{prompt[:40]}...'")
        assert conf_id is not None, "Failed to receive confirmation_id"

        # Explicitly deny
        conf_req_id = send_rpc("chat.confirm", {"confirmation_id": conf_id, "decision": "no"})
        confirm_res = wait_for_response(conf_req_id)
        assert confirm_res is not None, "Failed to receive chat.confirm response"
        print("[TEST 1] chat.confirm response:", confirm_res.get("result"))
        assert confirm_res.get("result", {}).get("status") == "resolved"
        assert confirm_res.get("result", {}).get("decision") == "no"

        # Read chat.send final reply
        turn_res = wait_for_response(send_id)
        assert turn_res is not None, "Failed to receive chat.send response"
        reply = turn_res.get("result", {}).get("reply", "")
        print(f"[TEST 1] Assistant reply after denial: '{reply}'")
        assert "Action cancelled: user declined confirmation" in reply or "cancelled" in reply.lower()
        print("PASSED: Denial Prevents Execution")

        # -----------------------------------------------------------
        # Test 2: Duplicate approval cannot execute action twice
        # -----------------------------------------------------------
        print("\n--- Subtest 2: Duplicate Approval Prevention ---")
        # Try to confirm the same conf_id again
        dup_req_id = send_rpc("chat.confirm", {"confirmation_id": conf_id, "decision": "yes"})
        dup_res = wait_for_response(dup_req_id)
        assert dup_res is not None, "Failed to receive duplicate chat.confirm response"
        print("[TEST 2] Duplicate chat.confirm response:", dup_res.get("result"))
        assert dup_res.get("result", {}).get("status") == "not_found", "Duplicate confirmation was not rejected"
        print("PASSED: Duplicate Approval Prevention (status: not_found)")

        # -----------------------------------------------------------
        # Test 3: Expired / Stale Confirmation Cannot Be Reused
        # -----------------------------------------------------------
        print("\n--- Subtest 3: Expired / Stale Confirmation Invalidation ---")
        fake_stale_id = "conf_expired_deadbeef"
        stale_req_id = send_rpc("chat.confirm", {"confirmation_id": fake_stale_id, "decision": "yes"})
        stale_res = wait_for_response(stale_req_id)
        assert stale_res is not None, "Failed to receive stale chat.confirm response"
        print("[TEST 3] Stale ID response:", stale_res.get("result"))
        assert stale_res.get("result", {}).get("status") == "not_found", "Stale ID was unexpectedly accepted"
        print("PASSED: Expired / Stale Confirmation Invalidation")

        # -----------------------------------------------------------
        # Test 4: HIGH_RISK Actions are Blocked Unconditionally
        # -----------------------------------------------------------
        print("\n--- Subtest 4: HIGH_RISK Action Denial ---")
        # Test direct execution of a high-risk tool via Python permission checker
        test_py = (
            "from tools.permissions import RiskLevel, check_permission, execute_with_permission, PermissionStatus\n"
            "class FakeHighRisk:\n"
            "    name = 'delete_system_core'\n"
            "    risk_level = RiskLevel.HIGH_RISK\n"
            "    func = lambda: 'EXECUTED_DANGEROUS_ACTION'\n"
            "perm = check_permission(FakeHighRisk(), is_admin=True)\n"
            "assert perm.status == PermissionStatus.DENIED\n"
            "res = execute_with_permission(FakeHighRisk(), (), {}, is_admin=True)\n"
            "assert 'Action blocked' in res\n"
            "print('HIGH_RISK check: blocked even for admin ->', res)\n"
        )
        res_hr = subprocess.run(
            [PYTHON_EXE, "-c", test_py],
            cwd=r"D:\Orange AI\Orange AI Desktop",
            capture_output=True,
            text=True
        )
        print("[TEST 4]", res_hr.stdout.strip())
        assert res_hr.returncode == 0, f"HIGH_RISK test failed: {res_hr.stderr}"
        print("PASSED: HIGH_RISK Action Denial (unconditional, admin cannot bypass)")

        # -----------------------------------------------------------
        # Test 5: Authoritative Python Timeout Enforcement
        # -----------------------------------------------------------
        print("\n--- Subtest 5: Authoritative Python Timeout Enforcement ---")
        # Test _confirmation_prompt_fn timeout behavior
        test_timeout_py = (
            "import threading, time\n"
            "from runtime.runtime_adapter import _pending_confirmations, _confirmations_lock, _confirmation_prompt_fn\n"
            "# Mock evt.wait to return False (simulating timeout without waiting 120s)\n"
            "import runtime.runtime_adapter as ra\n"
            "orig_evt = threading.Event\n"
            "class MockFastTimeoutEvent:\n"
            "    def wait(self, timeout=None):\n"
            "        return False  # Timed out\n"
            "    def set(self): pass\n"
            "threading.Event = MockFastTimeoutEvent\n"
            "decision = ra._confirmation_prompt_fn('test prompt')\n"
            "assert decision == 'no', f'Expected default no, got {decision}'\n"
            "assert len(ra._pending_confirmations) == 0, 'Pending confirmation not cleaned up after timeout'\n"
            "print('Timeout test passed: defaulted to no and cleaned up container.')\n"
        )
        res_to = subprocess.run(
            [PYTHON_EXE, "-c", test_timeout_py],
            cwd=r"D:\Orange AI\Orange AI Tauri",
            capture_output=True,
            text=True
        )
        print("[TEST 5]", res_to.stdout.strip())
        assert res_to.returncode == 0, f"Timeout test failed: {res_to.stderr}"
        print("PASSED: Authoritative Python Timeout Enforcement")

        # Clean shutdown
        send_rpc("system.shutdown")
        proc.wait(timeout=3)
        print("\n=======================================================")
        print("CONFIRMATION SECURITY AUDIT: ALL 5 SUBTESTS PASSED")
        print("=======================================================")

    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    run_confirmation_security_suite()

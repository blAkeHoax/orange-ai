"""
test_phase4_adapter_methods.py - Verify new Phase 4 JSON-RPC adapter operations:
1. chat.history
2. memory.remember
3. activity.get
"""
import os
import sys
import json
import time
import subprocess

ADAPTER_SCRIPT = r"D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py"
PYTHON_EXE = r"D:\Orange AI\Orange AI Desktop\venv\Scripts\python.exe"

def run_test():
    proc = subprocess.Popen(
        [PYTHON_EXE, ADAPTER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    req_id = 1
    def send_rpc(method, params=None):
        nonlocal req_id
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        req_id += 1
        line = proc.stdout.readline()
        return json.loads(line)

    try:
        # Drain ready notification
        ready_line = proc.stdout.readline()
        ready_evt = json.loads(ready_line)
        print("[TEST] Received ready:", ready_evt.get("method"))

        # 1. Test chat.history
        res = send_rpc("chat.history", {"limit": 10})
        print(f"[TEST] chat.history returned {len(res.get('result', []))} records")
        assert "result" in res, f"chat.history failed: {res}"

        # 2. Test memory.remember
        res_mem = send_rpc("memory.remember", {"fact": "Orange AI Desktop 2.0 integration active"})
        print("[TEST] memory.remember result:", res_mem.get("result"))
        assert res_mem.get("result", {}).get("success") is True, f"memory.remember failed: {res_mem}"

        # 3. Test activity.get
        res_act = send_rpc("activity.get", {})
        act = res_act.get("result", {})
        print(f"[TEST] activity.get returned logs={len(act.get('logs', []))}, jobs={len(act.get('job_steps', []))}, convs={len(act.get('conversations', []))}")
        assert "logs" in act and "job_steps" in act and "conversations" in act, f"activity.get missing keys: {res_act}"

        # Clean shutdown
        send_rpc("system.shutdown")
        proc.wait(timeout=3)
        print("[TEST] Phase 4 adapter methods PASSED!")

    finally:
        if proc.poll() is None:
            proc.kill()

if __name__ == "__main__":
    run_test()

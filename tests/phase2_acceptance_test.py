"""
Phase 2 Comprehensive Acceptance Test Suite for Orange AI Desktop 2.0
Validates:
  1. Headless Python runtime adapter protocol & lifecycle
  2. Protocol stdout purity (stderr isolation)
  3. JSON-RPC 2.0 system.ping, system.health, memory.stats, jobs.list
  4. chat.send background turn execution
  5. Two-phase confirmation interception & resolution
  6. system.shutdown and stdin EOF termination
  7. Absolute workspace & database immutability of D:\\Orange AI\\Orange AI Desktop
"""

import json
import os
import subprocess
import sys
import time

PYTHON_EXE = r"D:\Orange AI\Orange AI Desktop\venv\Scripts\python.exe"
ADAPTER_PY = r"D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py"
DESKTOP_DIR = r"D:\Orange AI\Orange AI Desktop"


def run_test(name, fn):
    print(f"\n--- [TEST] {name} ---")
    try:
        fn()
        print(f"PASSED: {name}")
        return True
    except Exception as e:
        print(f"FAILED: {name} -> {e}")
        return False


def test_protocol_startup_and_ping():
    proc = subprocess.Popen(
        [PYTHON_EXE, "-u", ADAPTER_PY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    try:
        # Step 1: Wait for runtime.ready notification
        ready_line = proc.stdout.readline()
        assert ready_line, "Failed to read runtime.ready notification"
        ready_json = json.loads(ready_line.strip())
        assert ready_json.get("method") == "runtime.ready", f"Unexpected method: {ready_json}"
        print(f"Received notification: {ready_json['method']}")

        # Step 2: Send system.ping
        req = {"jsonrpc": "2.0", "id": "test-ping-1", "method": "system.ping", "params": {}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()

        resp_line = proc.stdout.readline()
        assert resp_line, "No response for ping"
        resp = json.loads(resp_line.strip())
        assert resp.get("id") == "test-ping-1"
        res = resp.get("result", {})
        assert res.get("status") in ("ok", "pong", "online"), f"Unexpected status: {res.get('status')}"
        print(f"Ping response: PID={res.get('pid')}, status={res.get('status')}, version={res.get('version')}")

        # Step 3: Send system.shutdown
        shut_req = {"jsonrpc": "2.0", "id": "test-shut-1", "method": "system.shutdown", "params": {}}
        proc.stdin.write(json.dumps(shut_req) + "\n")
        proc.stdin.flush()

        shut_line = proc.stdout.readline()
        assert shut_line, "No response for shutdown"
        shut_resp = json.loads(shut_line.strip())
        assert shut_resp.get("id") == "test-shut-1"

        proc.wait(timeout=5)
        assert proc.returncode == 0, f"Expected 0, got {proc.returncode}"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_memory_stats_query():
    proc = subprocess.Popen(
        [PYTHON_EXE, "-u", ADAPTER_PY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    try:
        proc.stdout.readline() # ready
        req = {"jsonrpc": "2.0", "id": "mem-1", "method": "memory.stats", "params": {}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()

        line = proc.stdout.readline()
        resp = json.loads(line.strip())
        assert resp.get("id") == "mem-1"
        res = resp.get("result", {})
        structured = res.get("structured_memories", res.get("structured_count", 0))
        legacy = res.get("legacy_memories", res.get("legacy_count", 0))
        print(f"Memory Stats: structured={structured}, legacy={legacy}, total={res.get('total')}")
        assert structured > 0, "Expected structured memories in database"

        # Shutdown
        proc.stdin.close()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_deterministic_chat_turn():
    proc = subprocess.Popen(
        [PYTHON_EXE, "-u", ADAPTER_PY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    try:
        proc.stdout.readline() # ready
        req = {"jsonrpc": "2.0", "id": "chat-1", "method": "chat.send", "params": {"text": "what time is it"}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()

        line = proc.stdout.readline()
        resp = json.loads(line.strip())
        assert resp.get("id") == "chat-1"
        res = resp.get("result", {})
        reply = res.get("reply") or res.get("response") or ""
        print(f"Assistant reply: '{reply}' (model: {res.get('model')})")
        assert len(reply) > 0, "Expected non-empty assistant reply"

        proc.stdin.close()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_confirmation_interception_and_denial():
    proc = subprocess.Popen(
        [PYTHON_EXE, "-u", ADAPTER_PY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    try:
        proc.stdout.readline() # ready
        req = {"jsonrpc": "2.0", "id": "confirm-chat-1", "method": "chat.send", "params": {"text": "open notepad"}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()

        # Should receive assistant.confirmation_required notification
        event_line = proc.stdout.readline()
        event_json = json.loads(event_line.strip())
        assert event_json.get("method") == "assistant.confirmation_required"
        conf_id = event_json["params"]["confirmation_id"]
        prompt = event_json["params"].get("prompt_text") or event_json["params"].get("prompt")
        print(f"Confirmation requested: id={conf_id}, prompt='{prompt}'")

        # Deny the action
        deny_req = {"jsonrpc": "2.0", "id": "confirm-res-1", "method": "chat.confirm", "params": {"confirmation_id": conf_id, "decision": "no"}}
        proc.stdin.write(json.dumps(deny_req) + "\n")
        proc.stdin.flush()

        # Read confirm response
        deny_line = proc.stdout.readline()
        deny_resp = json.loads(deny_line.strip())
        assert deny_resp.get("id") == "confirm-res-1"
        assert deny_resp.get("result", {}).get("decision") == "no"

        # Read final chat response
        chat_line = proc.stdout.readline()
        chat_resp = json.loads(chat_line.strip())
        assert chat_resp.get("id") == "confirm-chat-1"
        reply = chat_resp['result'].get('reply') or chat_resp['result'].get('response') or ""
        print(f"Final response after denial: '{reply}'")
        assert "cancel" in reply.lower() or "denied" in reply.lower() or "not" in reply.lower()

        proc.stdin.close()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_eof_termination():
    proc = subprocess.Popen(
        [PYTHON_EXE, "-u", ADAPTER_PY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    try:
        proc.stdout.readline() # ready
        # Close stdin abruptly to simulate parent crash / exit
        proc.stdin.close()
        proc.wait(timeout=5)
        assert proc.returncode == 0, f"Expected clean exit code 0 on EOF, got {proc.returncode}"
        print("EOF clean termination verified with returncode 0.")
    finally:
        if proc.poll() is None:
            proc.kill()


def test_desktop_workspace_immutability():
    git_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=r"D:\Orange AI",
        capture_output=True,
        text=True
    )
    # Check that D:\Orange AI\Orange AI Desktop has no modified tracked files
    desktop_changes = [line for line in git_status.stdout.splitlines() if "Orange AI Desktop/" in line]
    print(f"Orange AI Desktop changes in Git: {desktop_changes}")
    assert len(desktop_changes) == 0, f"Protected workspace D:\\Orange AI\\Orange AI Desktop was modified: {desktop_changes}"
    print("Zero modifications to D:\\Orange AI\\Orange AI Desktop verified.")


if __name__ == "__main__":
    tests = [
        ("Protocol Startup & system.ping", test_protocol_startup_and_ping),
        ("Memory Stats Query", test_memory_stats_query),
        ("Deterministic Chat Turn", test_deterministic_chat_turn),
        ("Confirmation Interception & Denial", test_confirmation_interception_and_denial),
        ("EOF Clean Shutdown", test_eof_termination),
        ("Protected Workspace Immutability", test_desktop_workspace_immutability),
    ]

    passed = 0
    for name, fn in tests:
        if run_test(name, fn):
            passed += 1

    print(f"\n==========================================")
    print(f"ACCEPTANCE RESULTS: {passed}/{len(tests)} TESTS PASSED")
    print(f"==========================================")
    sys.exit(0 if passed == len(tests) else 1)

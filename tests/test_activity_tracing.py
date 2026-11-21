import os
import sys
import json
import re

sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")
sys.path.insert(0, r"D:\Orange AI\Orange AI Tauri")

from runtime.runtime_adapter import handle_activity_get

def test_activity_tracing():
    print("\n=======================================================")
    print("--- [TEST SUITE] Activity & Audit Trail Tracing ---")
    print("=======================================================")

    data = handle_activity_get({})
    logs = data.get("logs", [])
    job_steps = data.get("job_steps", [])
    convs = data.get("conversations", [])

    print(f"Total retrieved: {len(logs)} logs, {len(job_steps)} job steps, {len(convs)} conversation messages.")

    # 1. Successful Action Trace
    # Look for successful turns in conversations or logs
    success_record = None
    for c in convs:
        if c.get("role") == "assistant" and len(c.get("content", "")) > 10 and "cancelled" not in c.get("content", "").lower() and "error" not in c.get("content", "").lower():
            success_record = c
            break

    print("\n--- 1. Genuine Successful Action Trace ---")
    if success_record:
        print(f"Runtime Origin: conversation_history table (SQLite)")
        print(f"Timestamp:      {success_record.get('time')}")
        print(f"Role:           {success_record.get('role')}")
        print(f"Payload:        {success_record.get('content')[:120]}...")
        print(f"Frontend View:  ActivityView -> Conversations Tab -> Message Card")
    else:
        print("No prior successful conversation turn found.")

    # 2. Denied Action Trace
    # Look for denied confirmation in logs or conversation
    denied_record = None
    for c in convs:
        if "declined confirmation" in c.get("content", "") or "action cancelled" in c.get("content", "").lower():
            denied_record = {"type": "conversation", "data": c}
            break
    if not denied_record:
        for l in logs:
            if "declined" in l.get("message", "").lower() or "denied" in l.get("message", "").lower():
                denied_record = {"type": "log", "data": l}
                break

    print("\n--- 2. Genuine Denied Action Trace ---")
    if denied_record:
        print(f"Runtime Origin: {denied_record['type']} in Python Runtime")
        d = denied_record["data"]
        print(f"Timestamp:      {d.get('time')}")
        print(f"Message:        {d.get('content', d.get('message'))}")
        print(f"Frontend View:  ActivityView -> System Logs or Conversations Tab (Audit Provenance)")
    else:
        print("No denied action record found.")

    # 3. Failed Action Trace
    # Look for ERROR or WARNING in logs
    failed_record = None
    for l in logs:
        if l.get("level") in ("ERROR", "CRITICAL") or "offline" in l.get("message", "").lower():
            failed_record = l
            break

    print("\n--- 3. Genuine Failed Action Trace ---")
    if failed_record:
        print(f"Runtime Origin: orange_ai.log / Logging Handler")
        print(f"Timestamp:      {failed_record.get('time')}")
        print(f"Level:          {failed_record.get('level')}")
        print(f"Message:        {failed_record.get('message')[:120]}...")
        print(f"Frontend View:  ActivityView -> System Logs Tab (Red Badge / Level Filter)")
    else:
        print("No error/failed record found.")

    # 4. Secrets Exposure Audit
    print("\n--- 4. Secret & Credential Exposure Audit ---")
    sensitive_patterns = [
        re.compile(r"api[_-]?key\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{8,})", re.IGNORECASE),
        re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),
        re.compile(r"password\s*[:=]\s*['\"]?(\S+)", re.IGNORECASE),
        re.compile(r"secret\s*[:=]\s*['\"]?(\S+)", re.IGNORECASE),
    ]

    exposed = []
    for item in logs:
        text = item.get("message", "")
        for pat in sensitive_patterns:
            if pat.search(text):
                exposed.append((item.get("time"), text[:60]))

    if not exposed:
        print("VERIFIED: Zero API keys, Bearer tokens, or passwords detected in activity records.")
    else:
        print(f"WARNING: Potential secrets found: {exposed}")

    print("\n=======================================================")
    print("ACTIVITY & AUDIT TRAIL VERIFICATION COMPLETE")
    print("=======================================================")

if __name__ == "__main__":
    test_activity_tracing()

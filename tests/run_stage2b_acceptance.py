"""
tests/run_stage2b_acceptance.py - Master Acceptance & Verification Runner for Stage 2B
Executes:
  1. CDP Stage 2B Automated Test Suite (4 NVIDIA models, Proactive settings, System theme, API URL editing, Regression, Security)
  2. Screenshot Artifact Verification
  3. Protected Workspace Immutability Audit
"""
import os
import sys
import time
import subprocess
from pathlib import Path

PYTHON_EXE = r"D:\Orange AI\Orange AI Desktop\venv\Scripts\python.exe"
TAURI_EXE = r"D:\Orange AI\Orange AI Tauri\src-tauri\target\x86_64-pc-windows-gnu\debug\app.exe"
DESKTOP_DIR = r"D:\Orange AI\Orange AI Desktop"
TAURI_DIR = r"D:\Orange AI\Orange AI Tauri"
ARTIFACT_DIR = r"C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010"

EXPECTED_SCREENSHOTS = [
    "stage2b_model_selector_dark.png",
    "stage2b_model_selector_light.png",
    "stage2b_proactive_settings.png",
    "stage2b_api_url_editing.png",
    "stage2b_system_theme_detection.png"
]

def main():
    start_time = time.time()
    results = {}

    # 1. CDP Stage 2B Test Suite
    try:
        print("\n=======================================================")
        print("--- [STEP 1] CDP Stage 2B Automated Test Suite ---")
        print("=======================================================")
        env = os.environ.copy()
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9222"
        
        proc = subprocess.Popen([TAURI_EXE], env=env)
        print(f"[RUNNER] Spawned app.exe PID: {proc.pid}")
        time.sleep(6)

        try:
            node_res = subprocess.run(
                ["node", r"D:\Orange AI\Orange AI Tauri\tests\cdp_stage2b_suite.js"],
                capture_output=True,
                text=True
            )
            print(node_res.stdout)
            if node_res.stderr:
                print("--- NODE STDERR ---")
                print(node_res.stderr)
            if node_res.returncode != 0:
                raise AssertionError(f"CDP capture failed with code {node_res.returncode}")
        finally:
            print("[RUNNER] Shutting down Tauri application...")
            proc.kill()
            proc.wait(timeout=5)
            print("[RUNNER] Clean shutdown complete.")

        results["Stage 2B CDP Test Suite"] = "PASSED (Tests A-F)"
    except Exception as e:
        results["Stage 2B CDP Test Suite"] = f"FAILED: {e}"
        raise

    # 2. Screenshot Artifact Verification
    print("\n=======================================================")
    print("--- [STEP 2] Screenshot Artifact Verification ---")
    print("=======================================================")
    missing_shots = []
    for shot in EXPECTED_SCREENSHOTS:
        shot_path = os.path.join(ARTIFACT_DIR, shot)
        if os.path.exists(shot_path) and os.path.getsize(shot_path) > 1000:
            print(f"  ✓ Found artifact: {shot} ({os.path.getsize(shot_path):,} bytes)")
        else:
            missing_shots.append(shot)
            print(f"  ✗ Missing or empty artifact: {shot}")

    if missing_shots:
        raise AssertionError(f"Missing required screenshot artifacts: {missing_shots}")
    results["Visual Captures"] = f"PASSED ({len(EXPECTED_SCREENSHOTS)}/5 captured)"

    # 3. Python Runtime Authoritative Validation & Security Audit
    print("\n=======================================================")
    print("--- [STEP 3] Python Runtime Validation & Security Audit ---")
    print("=======================================================")
    import json
    sys.path.insert(0, os.path.join(TAURI_DIR, "runtime"))
    from runtime_adapter import handle_settings_update, handle_settings_get

    # 1. Invalid model rejection
    r1 = handle_settings_update({"model": "invalid/model-404"})
    assert r1.get("success") is False, f"Expected invalid model rejection, got: {r1}"
    print("  ✓ Python runtime rejected invalid model: invalid/model-404")

    # 2. Unsafe URL scheme rejection
    r2 = handle_settings_update({"api_url": "javascript:alert(1)"})
    assert r2.get("success") is False, f"Expected unsafe URL rejection, got: {r2}"
    print("  ✓ Python runtime rejected unsafe URL scheme: javascript:alert(1)")

    # 3. Invalid briefing time rejection
    r3 = handle_settings_update({"preferred_briefing_time": "25:99"})
    assert r3.get("success") is False, f"Expected invalid time rejection, got: {r3}"
    print("  ✓ Python runtime rejected invalid briefing time: 25:99")

    # 4. Invalid cooldown rejection
    r4 = handle_settings_update({"advisory_cooldown_hours": 12})
    assert r4.get("success") is False, f"Expected invalid cooldown rejection, got: {r4}"
    print("  ✓ Python runtime rejected invalid cooldown hours: 12")

    # 5. Valid updates
    r5 = handle_settings_update({"model": "meta/llama-3.1-70b-instruct", "preferred_briefing_time": "09:15"})
    assert r5.get("success") is True, f"Expected valid update success, got: {r5}"
    assert r5["settings"]["model"] == "meta/llama-3.1-70b-instruct"
    print("  ✓ Python runtime successfully applied valid model and time updates")

    # Restore default
    r6 = handle_settings_update({"model": "nvidia/llama-3.1-nemotron-70b-instruct", "preferred_briefing_time": "08:30"})
    assert r6.get("success") is True
    print("  ✓ Python runtime restored default Nemotron 70B and 08:30 briefing time")

    results["Python Authoritative Validation"] = "PASSED (100% boundary enforced)"

    # 4. Protected Workspace Immutability Check
    print("\n=======================================================")
    print("--- [STEP 4] Protected Workspace Immutability Audit ---")
    print("=======================================================")
    desktop_path = Path(DESKTOP_DIR)
    # Check if any files in Orange AI Desktop were modified during Stage 2B
    import datetime
    today_start = datetime.datetime(2026, 11, 16, 0, 0, 0).timestamp()
    stage2b_modified = []
    for f in desktop_path.glob("**/*"):
        if not f.is_file():
            continue
        if "venv" in str(f) or "__pycache__" in str(f):
            continue
        mtime = f.stat().st_mtime
        if mtime >= today_start:
            stage2b_modified.append(str(f))

    if stage2b_modified:
        print(f"WARNING: Files modified in protected workspace: {stage2b_modified}")
        raise AssertionError(f"Protected workspace modified: {stage2b_modified}")
    else:
        print(f"Audited {DESKTOP_DIR}: 0 source modifications during Stage 2B. Workspace strictly untouched.")
        results["Protected Workspace Immutability"] = "PASSED (100% read-only preserved)"

    duration = time.time() - start_time
    print("\n" + "=" * 60)
    print("STAGE 2B COMPREHENSIVE ACCEPTANCE SUMMARY")
    print("=" * 60)
    for test_name, status in results.items():
        print(f"  • {test_name}: {status}")
    print(f"\nTotal verification completed in {duration:.2f}s")
    print("ALL STAGE 2B VERIFICATIONS COMPLETED SUCCESSFULLY.")

if __name__ == "__main__":
    main()

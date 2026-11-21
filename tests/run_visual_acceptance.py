# tests/run_visual_acceptance.py
import subprocess
import os
import sys
import time

TAURI_EXE = r"D:\Orange AI\Orange AI Tauri\src-tauri\target\x86_64-pc-windows-gnu\debug\app.exe"
SUITE_JS = r"D:\Orange AI\Orange AI Tauri\tests\cdp_visual_suite.js"

def main():
    if not os.path.exists(TAURI_EXE):
        print(f"Error: {TAURI_EXE} does not exist.")
        sys.exit(1)

    env = os.environ.copy()
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9222"

    print(f"[RUNNER] Launching {TAURI_EXE} with CDP enabled on port 9222...")
    proc = subprocess.Popen([TAURI_EXE], env=env)
    print(f"[RUNNER] Process spawned with PID: {proc.pid}")

    time.sleep(2)

    try:
        print(f"[RUNNER] Executing Node CDP test suite: {SUITE_JS}...")
        node_res = subprocess.run(["node", SUITE_JS], capture_output=True, text=True)
        print("\n--- NODE STDOUT ---")
        print(node_res.stdout)
        if node_res.stderr:
            print("\n--- NODE STDERR ---")
            print(node_res.stderr)
        
        if node_res.returncode != 0:
            print(f"[RUNNER] Node suite failed with code {node_res.returncode}")
            sys.exit(node_res.returncode)
        else:
            print("[RUNNER] Node suite passed successfully!")
    finally:
        print("[RUNNER] Terminating Tauri application...")
        proc.kill()
        proc.wait(timeout=5)
        print("[RUNNER] Clean shutdown complete.")

if __name__ == "__main__":
    main()

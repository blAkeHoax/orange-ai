import os
import sys
import time
import json
import subprocess
import urllib.request
import urllib.error

APP_PATH = r"C:\Users\User\AppData\Local\Orange AI\app.exe"
ADAPTER_PATH = r"C:\Users\User\AppData\Local\Orange AI\resources\runtime\runtime_adapter.exe"

def get_running_processes():
    cmd = ["powershell", "-NoProfile", "-Command",
           "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('app.exe', 'runtime_adapter.exe') } | "
           "Select-Object ProcessId, Name, ExecutablePath, CommandLine | ConvertTo-Json -Compress"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = res.stdout.strip()
    if not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return [data]
        return data
    except Exception as e:
        print(f"Error parsing process json: {e}, raw: {out}")
        return []

def main():
    print("=== ORANGE AI 2.0 INSTALLED APP VALIDATION ===")
    
    # 1. Clean any lingering processes
    procs = get_running_processes()
    for p in procs:
        print(f"Terminating lingering process {p.get('Name')} (PID {p.get('ProcessId')})")
        subprocess.run(["taskkill", "/F", "/PID", str(p.get("ProcessId"))], capture_output=True)
    time.sleep(1)

    # 2. Launch installed app with remote debugging port enabled
    env = os.environ.copy()
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9222"
    
    print(f"Launching {APP_PATH}...")
    app_proc = subprocess.Popen([APP_PATH], env=env)
    print(f"Spawned app.exe PID: {app_proc.pid}")
    
    # Wait for process initialization
    time.sleep(4)
    
    # 3. Inspect process tree
    active_procs = get_running_processes()
    print(f"\nActive processes detected ({len(active_procs)}):")
    app_found = False
    adapter_found = False
    for p in active_procs:
        print(f"  PID {p.get('ProcessId')}: {p.get('Name')} -> {p.get('ExecutablePath')}")
        if p.get("Name") == "app.exe" and p.get("ExecutablePath") == APP_PATH:
            app_found = True
        if p.get("Name") == "runtime_adapter.exe" and p.get("ExecutablePath") == ADAPTER_PATH:
            adapter_found = True

    print(f"\nProcess Check:")
    print(f"  app.exe running from installed path: {app_found}")
    print(f"  runtime_adapter.exe running from bundled runtime path: {adapter_found}")
    
    # 4. Single-instance protection check
    print("\n--- Single-Instance Mutex Check ---")
    start_time = time.time()
    second_proc = subprocess.run([APP_PATH], capture_output=True, text=True, timeout=10)
    elapsed = time.time() - start_time
    print(f"Second instance terminated with exit code: {second_proc.returncode} in {elapsed:.2f}s")
    
    # Verify process count is still exactly 1 app.exe and 1 runtime_adapter.exe
    post_second_procs = get_running_processes()
    app_count = sum(1 for p in post_second_procs if p.get("Name") == "app.exe")
    adapter_count = sum(1 for p in post_second_procs if p.get("Name") == "runtime_adapter.exe")
    print(f"Active app.exe count: {app_count} (expected 1)")
    print(f"Active runtime_adapter.exe count: {adapter_count} (expected 1)")

    # 5. Connect to WebView2 CDP to inspect application state
    print("\n--- WebView2 CDP Inspection ---")
    try:
        req = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5)
        targets = json.loads(req.read().decode())
        print(f"CDP Targets ({len(targets)}):")
        for t in targets:
            print(f"  Target: {t.get('title')} | Type: {t.get('type')} | URL: {t.get('url')}")
    except Exception as e:
        print(f"CDP connection failed: {e}")

    # 6. Terminate app.exe and verify Job Object clean shutdown (no orphan runtime_adapter.exe)
    print("\n--- Process Termination & Job Object Orphan Verification ---")
    print(f"Terminating app.exe (PID {app_proc.pid})...")
    subprocess.run(["taskkill", "/F", "/PID", str(app_proc.pid)], capture_output=True)
    time.sleep(2)
    
    post_term_procs = get_running_processes()
    print(f"Processes remaining after app.exe termination: {len(post_term_procs)}")
    for p in post_term_procs:
        print(f"  ORPHAN DETECTED: PID {p.get('ProcessId')}: {p.get('Name')}")
        subprocess.run(["taskkill", "/F", "/PID", str(p.get("ProcessId"))], capture_output=True)
        
    success = (app_found and adapter_found and second_proc.returncode == 0 and 
               app_count == 1 and adapter_count == 1 and len(post_term_procs) == 0)
    print(f"\nOVERALL VALIDATION RESULT: {'PASS' if success else 'FAIL'}")

if __name__ == "__main__":
    main()

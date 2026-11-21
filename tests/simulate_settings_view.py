import subprocess
import json

PYTHON_EXE = r"D:\Orange AI\Orange AI Desktop\venv\Scripts\python.exe"
ADAPTER_SCRIPT = r"D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py"

proc = subprocess.Popen(
    [PYTHON_EXE, ADAPTER_SCRIPT],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

def rpc(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)

try:
    ready = proc.stdout.readline()
    print("Ready:", ready.strip())

    p_res = rpc("system.ping", req_id=1)
    print("\nsystem.ping response:")
    print(json.dumps(p_res, indent=2))

    h_res = rpc("system.health", req_id=2)
    print("\nsystem.health response:")
    print(json.dumps(h_res, indent=2))

    s_res = rpc("settings.get", req_id=3)
    print("\nsettings.get response:")
    print(json.dumps(s_res, indent=2))

finally:
    proc.kill()

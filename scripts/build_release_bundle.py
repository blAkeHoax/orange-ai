import os
import sys
import subprocess

MINGW_BIN = r"C:\Users\User\AppData\Local\llvm-mingw-20261020-ucrt-x86_64\bin"
TAURI_DIR = r"D:\Orange AI\Orange AI Tauri"

def main():
    env = os.environ.copy()
    env["PATH"] = MINGW_BIN + os.pathsep + env.get("PATH", "")
    
    print("=== BUILDING TAURI RELEASE & NSIS BUNDLE ===")
    cmd = ["npm.cmd", "run", "tauri", "build", "--", "--target", "x86_64-pc-windows-gnu"]
    res = subprocess.run(cmd, cwd=TAURI_DIR, env=env)
    if res.returncode != 0:
        print(f"Build failed with exit code: {res.returncode}")
        sys.exit(res.returncode)
    print("Build succeeded!")

if __name__ == "__main__":
    main()

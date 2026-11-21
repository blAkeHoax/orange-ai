import os
import sys
import time
import subprocess
import json

INSTALL_DIR = r"C:\Users\User\AppData\Local\Orange AI"
UNINSTALLER = os.path.join(INSTALL_DIR, "uninstall.exe")
INSTALLER = r"D:\Orange AI\Orange AI Tauri\src-tauri\target\x86_64-pc-windows-gnu\release\bundle\nsis\Orange AI_2.0.0_x64-setup.exe"
DB_PATH = os.path.join(INSTALL_DIR, "memory.db")
SETTINGS_PATH = os.path.join(INSTALL_DIR, "gui_settings.json")

def main():
    print("=== WORKSTREAM G & H: LIFECYCLE & DATA PRESERVATION AUDIT ===")
    
    # 0. Check pre-uninstall state
    assert os.path.exists(UNINSTALLER), f"Uninstaller missing: {UNINSTALLER}"
    assert os.path.exists(DB_PATH), f"Database missing: {DB_PATH}"
    db_size_before = os.path.getsize(DB_PATH)
    print(f"Pre-uninstall database size: {db_size_before} bytes")
    
    # 1. Run uninstaller silently
    print(f"\n1. Executing silent uninstaller: {UNINSTALLER} /S ...")
    res = subprocess.run([UNINSTALLER, "/S"], capture_output=True, text=True)
    time.sleep(4)
    print("Uninstaller process completed.")
    
    # 2. Verify binary removal
    app_exe = os.path.join(INSTALL_DIR, "app.exe")
    runtime_exe = os.path.join(INSTALL_DIR, "resources", "runtime", "runtime_adapter.exe")
    app_exists = os.path.exists(app_exe)
    runtime_exists = os.path.exists(runtime_exe)
    print(f"Post-uninstall app.exe exists: {app_exists} (expected False)")
    print(f"Post-uninstall runtime_adapter.exe exists: {runtime_exists} (expected False)")
    
    # 3. Verify data preservation
    db_exists = os.path.exists(DB_PATH)
    settings_exists = os.path.exists(SETTINGS_PATH)
    db_size_after = os.path.getsize(DB_PATH) if db_exists else 0
    print(f"Post-uninstall memory.db exists: {db_exists} (expected True)")
    print(f"Post-uninstall memory.db size: {db_size_after} bytes (matches before: {db_size_before == db_size_after})")
    print(f"Post-uninstall gui_settings.json exists: {settings_exists} (expected True)")
    
    # 4. Re-run installer silently (Upgrade/Reinstall test)
    print(f"\n2. Executing silent reinstall: {INSTALLER} /S ...")
    res_inst = subprocess.run([INSTALLER, "/S"], capture_output=True, text=True)
    time.sleep(5)
    print("Installer process completed.")
    
    # 5. Verify restored binaries
    app_restored = os.path.exists(app_exe)
    runtime_restored = os.path.exists(runtime_exe)
    db_size_reinstall = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    
    print(f"Post-reinstall app.exe exists: {app_restored} (expected True)")
    print(f"Post-reinstall runtime_adapter.exe exists: {runtime_restored} (expected True)")
    print(f"Post-reinstall memory.db size: {db_size_reinstall} bytes (matches original: {db_size_reinstall == db_size_before})")
    
    success = (not app_exists and not runtime_exists and db_exists and 
               db_size_before == db_size_after and app_restored and runtime_restored and
               db_size_reinstall == db_size_before)
    
    print(f"\nLIFECYCLE & PRESERVATION RESULT: {'PASS' if success else 'FAIL'}")

if __name__ == "__main__":
    main()

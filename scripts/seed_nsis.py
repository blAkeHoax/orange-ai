"""
scripts/seed_nsis.py - Seed the local Tauri NSIS cache in %LOCALAPPDATA%\\tauri\\NSIS
"""

import os
import sys
import zipfile
import hashlib
import requests

LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA", r"C:\Users\User\AppData\Local")
TAURI_CACHE = os.path.join(LOCAL_APP_DATA, "tauri")
NSIS_DIR = os.path.join(TAURI_CACHE, "NSIS")

NSIS_ZIP_URL = "https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.13/nsis-3.13.zip"
NSIS_ZIP_SHA1 = "db14f8af2ea346b786c6ae19343f61aaf5e09b8e"

UTILS_DLL_URL = "https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll"
UTILS_DLL_SHA1 = "75197fee3c6a814fe035788d1c34ead39349b860"


def download_file(url, target_path, expected_sha1=None):
    print(f"Downloading {url} -> {target_path}...")
    headers = {"User-Agent": "Tauri-NSIS-Seeder/1.0"}
    res = requests.get(url, headers=headers, stream=True, timeout=60)
    res.raise_for_status()

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    h = hashlib.sha1()
    with open(target_path, "wb") as f:
        for chunk in res.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                h.update(chunk)

    actual_sha1 = h.hexdigest().lower()
    print(f"Downloaded: {actual_sha1}")
    if expected_sha1 and actual_sha1 != expected_sha1.lower():
        raise ValueError(f"Hash mismatch! Expected {expected_sha1}, got {actual_sha1}")
    return target_path


def seed_nsis():
    print(f"Seeding NSIS in: {NSIS_DIR}")
    os.makedirs(TAURI_CACHE, exist_ok=True)
    os.makedirs(NSIS_DIR, exist_ok=True)

    zip_path = os.path.join(TAURI_CACHE, "nsis-3.13.zip")
    if not os.path.exists(zip_path):
        download_file(NSIS_ZIP_URL, zip_path, NSIS_ZIP_SHA1)

    print(f"Extracting {zip_path} into {NSIS_DIR}...")
    with zipfile.ZipFile(zip_path, "r") as z:
        # Check zip root
        namelist = z.namelist()
        has_root = any(n.startswith("nsis-3.13/") for n in namelist)
        if has_root:
            # Extract and move if needed
            for member in z.infolist():
                # strip top-level nsis-3.13/ prefix if present
                rel_path = member.filename
                if rel_path.startswith("nsis-3.13/"):
                    rel_path = rel_path[len("nsis-3.13/"):]
                if not rel_path:
                    continue
                dest_path = os.path.join(NSIS_DIR, rel_path)
                if member.is_dir():
                    os.makedirs(dest_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with z.open(member) as src, open(dest_path, "wb") as dst:
                        dst.write(src.read())
        else:
            z.extractall(NSIS_DIR)

    # Ensure nsis_tauri_utils.dll is in Plugins/x86-unicode/additional/ and Plugins/x86-unicode/
    plugins_additional_dir = os.path.join(NSIS_DIR, "Plugins", "x86-unicode", "additional")
    os.makedirs(plugins_additional_dir, exist_ok=True)
    utils_dll_target = os.path.join(plugins_additional_dir, "nsis_tauri_utils.dll")
    download_file(UTILS_DLL_URL, utils_dll_target, UTILS_DLL_SHA1)

    plugins_dir = os.path.join(NSIS_DIR, "Plugins", "x86-unicode")
    import shutil
    shutil.copy2(utils_dll_target, os.path.join(plugins_dir, "nsis_tauri_utils.dll"))

    # Verify all 13 critical files required by tauri_bundler
    critical_files = [
        "Bin/makensis.exe",
        "Stubs/lzma-x86-unicode",
        "Stubs/lzma_solid-x86-unicode",
        "Plugins/x86-unicode/additional/nsis_tauri_utils.dll",
        "Include/MUI2.nsh",
        "Include/FileFunc.nsh",
        "Include/x64.nsh",
        "Include/nsDialogs.nsh",
        "Include/WinMessages.nsh",
        "Include/Win/COM.nsh",
        "Include/Win/Propkey.nsh",
        "Include/Win/RestartManager.nsh",
        "NSIS.exe",
    ]

    print("\n[VERIFICATION] Verifying all critical Tauri NSIS files:")
    all_ok = True
    for rel in critical_files:
        full_p = os.path.join(NSIS_DIR, rel.replace("/", os.sep))
        exists = os.path.exists(full_p)
        status = "OK" if exists else "MISSING"
        if not exists:
            all_ok = False
        print(f"  [{status}] {rel}")

    if all_ok:
        print("\n[SUCCESS] All critical NSIS files verified present!")
    else:
        raise RuntimeError("Some critical NSIS files are missing!")


if __name__ == "__main__":
    seed_nsis()

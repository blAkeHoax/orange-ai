"""
Automated Visual Acceptance & Screenshot Capture Suite for Orange AI Desktop 2.0 (Phase 3)
Captures:
  1. Home Dark (1024x720)
  2. Home Light (1024x720)
  3. Expanded Navigation Drawer Dark (1024x720)
  4. Expanded Navigation Drawer Light (1024x720)
  5. Responsive scaling: 960x600, 1120x750, 1440x900
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from PIL import ImageGrab

TAURI_EXE = r"D:\Orange AI\Orange AI Tauri\src-tauri\target\x86_64-pc-windows-gnu\debug\app.exe"
OUT_DIR = r"D:\Orange AI\Orange AI Tauri\screenshots"
ARTIFACTS_DIR = r"C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010"

user32 = ctypes.windll.user32

# Virtual key constants
VK_MENU = 0x12       # Alt
VK_T = 0x54          # T
VK_M = 0x4D          # M
VK_ESCAPE = 0x1B     # Esc
KEYEVENTF_KEYUP = 0x0002


def press_hotkey(mod_vk, key_vk):
    """Simulate key combination like Alt+T or Alt+M."""
    user32.keybd_event(mod_vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(key_vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(key_vk, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)
    user32.keybd_event(mod_vk, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.3)


def send_escape():
    user32.keybd_event(VK_ESCAPE, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.3)


def find_orange_window():
    """Find the top-level window for Orange AI."""
    found_hwnd = None

    def enum_windows_proc(hwnd, lParam):
        nonlocal found_hwnd
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                if buff.value == "Orange AI":
                    found_hwnd = hwnd
                    return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
    return found_hwnd


def get_window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def resize_window(hwnd, width, height):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    user32.MoveWindow(hwnd, rect.left, rect.top, width, height, True)
    time.sleep(0.5)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ('bmiHeader', BITMAPINFOHEADER),
        ('bmiColors', wintypes.DWORD * 3),
    ]


def capture_window_gdi(hwnd, filename):
    os.makedirs(OUT_DIR, exist_ok=True)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid window dimensions: {w}x{h}")

    print(f"Capturing window {hwnd} ({w}x{h}) via Win32 GDI -> {filename}")

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    ctypes.windll.gdi32.SelectObject(mem_dc, bmp)

    # PW_RENDERFULLCONTENT = 2
    res = user32.PrintWindow(hwnd, mem_dc, 2)
    if not res:
        res = user32.PrintWindow(hwnd, mem_dc, 0)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = (ctypes.c_char * (w * h * 4))()
    ctypes.windll.gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    from PIL import Image
    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1)
    img = img.convert('RGB')

    out_path = os.path.join(OUT_DIR, filename)
    img.save(out_path)

    if os.path.exists(ARTIFACTS_DIR):
        artifact_path = os.path.join(ARTIFACTS_DIR, filename)
        shutil.copy(out_path, artifact_path)

    ctypes.windll.gdi32.DeleteObject(bmp)
    ctypes.windll.gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    print(f"Saved: {out_path}")
    return out_path


def find_render_window(top_hwnd):
    """Find the HWND responsible for rendering the webview content."""
    render_hwnd = None

    def enum_child(hwnd, lParam):
        nonlocal render_hwnd
        cls_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_name, 256)
        if cls_name.value == "Chrome_RenderWidgetHostHWND":
            render_hwnd = hwnd
            return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(top_hwnd, WNDENUMPROC(enum_child), 0)
    return render_hwnd or top_hwnd


def click_window(top_hwnd, rel_x, rel_y):
    """Click at relative coordinates inside the window."""
    render_hwnd = find_render_window(top_hwnd)
    rect = wintypes.RECT()
    user32.GetWindowRect(render_hwnd, ctypes.byref(rect))
    screen_x = rect.left + rel_x
    screen_y = rect.top + rel_y
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.4)


def capture_window_gdi(hwnd, filename):
    os.makedirs(OUT_DIR, exist_ok=True)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid window dimensions: {w}x{h}")

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    ctypes.windll.gdi32.SelectObject(mem_dc, bmp)

    # PW_RENDERFULLCONTENT = 2
    res = user32.PrintWindow(hwnd, mem_dc, 2)
    if not res:
        res = user32.PrintWindow(hwnd, mem_dc, 0)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = (ctypes.c_char * (w * h * 4))()
    ctypes.windll.gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    from PIL import Image
    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')

    out_path = os.path.join(OUT_DIR, filename)
    img.save(out_path)

    if os.path.exists(ARTIFACTS_DIR):
        artifact_path = os.path.join(ARTIFACTS_DIR, filename)
        shutil.copy(out_path, artifact_path)

    ctypes.windll.gdi32.DeleteObject(bmp)
    ctypes.windll.gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    print(f"Captured {filename}: ({w}x{h}) -> {out_path}")
    return out_path


def capture_window(top_hwnd, filename):
    render_hwnd = find_render_window(top_hwnd)
    return capture_window_gdi(render_hwnd, filename)


def send_ui_command(cmd_dict):
    """Write command to UI command control file for adapter watcher."""
    cmd_file = r"D:\Orange AI\Orange AI Tauri\ui_command.json"
    with open(cmd_file, "w", encoding="utf-8") as f:
        json.dump(cmd_dict, f)
    time.sleep(0.8)


def run_visual_acceptance():
    print("--- [VISUAL ACCEPTANCE] Starting Orange AI Tauri Application ---")
    proc = subprocess.Popen([TAURI_EXE], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        # Wait up to 15s for window to initialize
        hwnd = None
        for i in range(30):
            time.sleep(0.5)
            hwnd = find_orange_window()
            if hwnd:
                break

        assert hwnd, "Failed to find 'Orange AI' top-level window!"
        print(f"Found Orange AI window HWND: {hwnd}")

        # Set to standard size 1024x720 and wait for WebView2 to finish initial render
        resize_window(hwnd, 1024, 720)
        print("Waiting 5s for WebView2 initial paint...")
        time.sleep(5.0)

        # 1. Capture Home Dark (Default)
        print("1. Capturing Home Dark (1024x720)...")
        capture_window(hwnd, "phase3_home_dark_1024x720.png")

        # 2. Open Navigation Drawer
        print("2. Opening Navigation Drawer...")
        send_ui_command({"command": "toggle_drawer", "open": True})
        capture_window(hwnd, "phase3_nav_expanded_dark_1024x720.png")

        # 3. Switch to Light Theme (while drawer open)
        print("3. Switching to Light Theme (expanded drawer)...")
        send_ui_command({"command": "set_theme", "theme": "light"})
        capture_window(hwnd, "phase3_nav_expanded_light_1024x720.png")

        # 4. Close Drawer to show Home Light
        print("4. Closing Navigation Drawer to show Home Light...")
        send_ui_command({"command": "toggle_drawer", "open": False})
        capture_window(hwnd, "phase3_home_light_1024x720.png")

        # 5. Switch back to Dark Theme for responsive tests
        print("5. Switching back to Dark Theme for responsive scaling...")
        send_ui_command({"command": "set_theme", "theme": "dark"})
        time.sleep(0.5)

        # 6. Test Responsive Scaling: 960x600
        print("6. Capturing Home Dark 960x600...")
        resize_window(hwnd, 960, 600)
        time.sleep(0.8)
        capture_window(hwnd, "phase3_home_dark_960x600.png")

        # 7. Test Responsive Scaling: 1120x750
        print("7. Capturing Home Dark 1120x750...")
        resize_window(hwnd, 1120, 750)
        time.sleep(0.8)
        capture_window(hwnd, "phase3_home_dark_1120x750.png")

        # 8. Test Responsive Scaling: 1440x900
        print("8. Capturing Home Dark 1440x900...")
        resize_window(hwnd, 1440, 900)
        time.sleep(0.8)
        capture_window(hwnd, "phase3_home_dark_1440x900.png")

        print("\nALL VISUAL SCREENSHOTS CAPTURED SUCCESSFULLY!")
        return True

    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    success = run_visual_acceptance()
    sys.exit(0 if success else 1)

"""
JARVIS Global Hotkey
Press Ctrl + Alt + Space  →  JARVIS wakes and starts listening
"""
import subprocess
import os
import urllib.request
import time
from pathlib import Path

from pynput import keyboard

APP_DIR   = Path(__file__).resolve().parent
BASE_DIR  = APP_DIR.parent if APP_DIR.name == "backend" else APP_DIR
START_BAT = BASE_DIR / "start_jarvis.bat"
APP_URL   = "http://localhost:5173"

# Track which keys are currently held
pressed = set()

HOTKEY = {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.Key.space}
HOTKEY_ALT = {keyboard.Key.ctrl_r, keyboard.Key.alt_r, keyboard.Key.space}


def is_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:8000/", timeout=1)
        return True
    except Exception:
        return False


def send_wake():
    try:
        req = urllib.request.Request(
            "http://localhost:8000/wake",
            data=b"",
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def get_browser_candidates():
    chrome_candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LocalAppData", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    browsers = []
    for path in chrome_candidates:
        if str(path) and path.exists():
            browsers.append(("chrome", path))
    browsers.append(("msedge", Path("msedge")))
    return browsers


def bring_jarvis_to_front():
    """Bring the JARVIS browser window to front, or open it if not found."""
    browser_names = "','".join(name for name, _ in get_browser_candidates())
    launch_browser = next((str(path) for name, path in get_browser_candidates() if name == "chrome"), "msedge")
    ps = (
        # Try to find the JARVIS window by title first, fall back to the localhost app window.
        f"$browserNames = @('{browser_names}'); "
        "$p = Get-Process -Name $browserNames -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowTitle -like '*J.A.R.V.I.S*' } | Select-Object -First 1; "
        "if (-not $p) { "
        "  $p = Get-Process -Name $browserNames -ErrorAction SilentlyContinue | "
        "  Where-Object { $_.MainWindowTitle -like '*localhost:5173*' } | Select-Object -First 1 "
        "}; "
        "if ($p) { "
        "  Add-Type @\"\n"
        "  using System;\n"
        "  using System.Runtime.InteropServices;\n"
        "  public class Win32 {\n"
        "    [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);\n"
        "    [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);\n"
        "  }\n"
        "\"@; "
        "  [Win32]::ShowWindow($p.MainWindowHandle, 9); "
        "  [Win32]::SetForegroundWindow($p.MainWindowHandle) "
        "} else { "
        f"  Start-Process '{launch_browser}' '--app={APP_URL}' "
        "}"
    )
    subprocess.Popen(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def activate_jarvis():
    if is_running():
        bring_jarvis_to_front()
        time.sleep(0.6)
        send_wake()
    else:
        subprocess.Popen(
            ["cmd", "/c", str(START_BAT)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=str(BASE_DIR),
        )


def check_hotkey():
    has_ctrl  = keyboard.Key.ctrl_l  in pressed or keyboard.Key.ctrl_r  in pressed
    has_alt   = keyboard.Key.alt_l   in pressed or keyboard.Key.alt_r   in pressed
    has_space = keyboard.Key.space   in pressed
    return has_ctrl and has_alt and has_space


def on_press(key):
    pressed.add(key)
    if check_hotkey():
        pressed.clear()
        activate_jarvis()


def on_release(key):
    pressed.discard(key)


if __name__ == "__main__":
    print("JARVIS hotkey: Ctrl + Alt + Space")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()

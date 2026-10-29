"""Double-click launcher: reuse existing local dashboard and log startup errors."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def browser_available():
    edge_locations = [Path(os.environ.get(key, "")) / "Microsoft/Edge/Application/msedge.exe"
                      for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    if any(p.is_file() for p in edge_locations):
        return True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).is_file()
    except Exception:
        return False


def existing_dashboard(address):
    try:
        with urllib.request.urlopen(address + "/api/status", timeout=1) as response:
            data = json.load(response)
        return isinstance(data, dict) and {"active_job", "browser_ready", "csrf_token"} <= data.keys()
    except (OSError, ValueError, urllib.error.HTTPError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.check_browser:
        return 0 if browser_available() else 1
    project = Path(__file__).resolve().parent.parent
    os.chdir(project)
    address = "http://127.0.0.1:8765"
    if existing_dashboard(address):
        webbrowser.open(address)
        return 0
    log_dir = project / "data"
    log_dir.mkdir(exist_ok=True)
    previous_streams = sys.stdout, sys.stderr
    with (log_dir / "launcher.log").open("a", encoding="utf-8") as log:
        sys.stdout = sys.stderr = log
        try:
            from .app import main as run_app
            run_app([])
        except Exception:
            import traceback
            traceback.print_exc()
            if os.name == "nt":
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0, "Không mở được FoodTour. Có thể cổng 8765 đang được ứng dụng khác sử dụng. "
                    "Chi tiết nằm trong data/launcher.log.", "FoodTour", 16)
            return 1
        finally:
            sys.stdout, sys.stderr = previous_streams
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

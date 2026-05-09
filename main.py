"""Entry point for the packaged executable.

Without args: launches the configuration GUI.
With --daemon: runs the OLED monitoring loop (used by 'Run at login' / 'Start monitor').
"""

import datetime
import sys
import traceback
from pathlib import Path


def _project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _log_crash(exc_type, exc_value, exc_tb) -> None:
    """Append uncaught exceptions to crash.log next to the executable.

    Without this, --noconsole builds die silently with no forensic trail.
    """
    try:
        path = _project_dir() / "crash.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.datetime.now().isoformat()} ===\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass


def _install_crash_logging() -> None:
    sys.excepthook = _log_crash
    # Tkinter callback exceptions go through report_callback_exception, not excepthook.
    try:
        import tkinter
        tkinter.Tk.report_callback_exception = lambda self, exc, val, tb: _log_crash(exc, val, tb)
    except Exception:
        pass


def main() -> None:
    _install_crash_logging()
    if "--daemon" in sys.argv:
        from gpu_oled import main as daemon_main
        daemon_main()
    else:
        import customtkinter as ctk
        from config_app import App
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        App().mainloop()


if __name__ == "__main__":
    main()

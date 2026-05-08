"""Entry point for the packaged executable.

Without args: launches the configuration GUI.
With --daemon: runs the OLED monitoring loop (used by 'Run at login' / 'Start monitor').
"""

import sys


def main() -> None:
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

"""Configuration GUI for the GPU OLED monitor."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import customtkinter as ctk
import psutil
import requests
import winreg

from gpu_backend import get_backend, list_gpus
from stats import STATS, current_lines, render_line


# Must match GAME in gpu_oled.py — duplicated to avoid importing the daemon
# module (and triggering its logging.basicConfig as a side effect).
GAMESENSE_GAME_ID = "GPU_MONITOR"


FROZEN = getattr(sys, "frozen", False)
PROJECT_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"
SCRIPT_FILE = PROJECT_DIR / "gpu_oled.py"
PID_FILE = PROJECT_DIR / "gpu_oled.pid"

DEFAULT_CONFIG = {
    "line1": "gpu_temp",
    "line2": "gpu_power",
    "alt_line1": "gpu_util",
    "alt_line2": "mem_used",
    "cycle_enabled": False,
    "cycle_seconds": 4,
    "gpu_id": "auto",
    "temp_warning_enabled": False,
    "temp_warning_threshold": 80,
    "overlay_x": 100,
    "overlay_y": 100,
    "power_warning_enabled": False,
    "power_warning_threshold": 600,
    "power_overlay_x": 100,
    "power_overlay_y": 210,
}


def daemon_command() -> list[str]:
    """Command-line tokens to launch the monitoring daemon.

    When packaged as a single .exe, run that exe with --daemon. Otherwise run
    pythonw.exe against the source script (no console window).
    """
    if FROZEN:
        return [sys.executable, "--daemon"]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pythonw), str(SCRIPT_FILE)]


def load_config() -> dict:
    try:
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def _find_daemon_processes() -> list:
    """All live daemon processes on the system, regardless of PID-file state.

    Catches orphans from older builds, renamed .exes, copies in other folders,
    and any python process whose command line touches gpu_oled.
    """
    me = os.getpid()
    me_parent = None
    try:
        me_parent = psutil.Process(me).ppid()
    except Exception:
        pass

    matches = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if pid == me or pid == me_parent:
                continue
            cmdline = proc.info.get("cmdline") or []
            joined = " ".join(cmdline).lower()
            name = (proc.info.get("name") or "").lower()
            # Broad match — anything whose name or cmdline references the
            # project's daemon. Catches `pythonw.exe gpu_oled.py`, the .exe
            # under any name, and renamed copies.
            tokens = ("gpu_oled", "gpu-oled-monitor", "gpu-oled-daemon")
            if any(t in name for t in tokens) or any(t in joined for t in tokens):
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def is_running() -> bool:
    return len(_find_daemon_processes()) > 0


def start_monitor() -> None:
    # Wipe any orphan daemons before spawning a fresh one so we never end up
    # with two pushing to the OLED at the same time.
    stop_monitor()
    subprocess.Popen(
        daemon_command(),
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _gamesense_address() -> str:
    core_props = (Path(os.environ["PROGRAMDATA"]) /
                  "SteelSeries" / "SteelSeries Engine 3" / "coreProps.json")
    return json.loads(core_props.read_text())["address"]


def _gg_remove_game() -> None:
    """Best-effort wipe of our GameSense registration.

    GG caches the last few screen frames and keeps replaying them after
    /remove_game (its own behavior, not ours). Counter that by pushing a
    handful of blank frames first so the cached cycle becomes blank/blank.
    """
    try:
        addr = _gamesense_address()
    except Exception:
        return
    blank_event = {
        "game": GAMESENSE_GAME_ID, "event": "GPU_STATS",
        "data": {"value": 0, "frame": {"line1": " ", "line2": " "}},
    }
    for _ in range(5):
        try:
            requests.post(f"http://{addr}/game_event", json=blank_event, timeout=2)
        except Exception:
            pass
        time.sleep(0.3)
    try:
        requests.post(f"http://{addr}/remove_game",
                      json={"game": GAMESENSE_GAME_ID}, timeout=3)
    except Exception:
        pass


def stop_monitor() -> None:
    procs = _find_daemon_processes()
    for proc in procs:
        try: proc.terminate()
        except Exception: pass
    if procs:
        gone, alive = psutil.wait_procs(procs, timeout=3)
        for proc in alive:
            try: proc.kill()
            except Exception: pass
    PID_FILE.unlink(missing_ok=True)
    _gg_remove_game()


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "GPU OLED Monitor"


def _autostart_command_line() -> str:
    """Quoted command-line string suitable for the Run registry value."""
    return subprocess.list2cmdline(daemon_command())


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _cleanup_legacy_scheduled_task() -> None:
    """Quietly remove the old schtasks entry from earlier versions, if present.

    No-op if the task doesn't exist or schtasks isn't available.
    """
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", "GPU OLED Monitor", "/f"],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def install_autostart() -> None:
    _cleanup_legacy_scheduled_task()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, _autostart_command_line())


def uninstall_autostart() -> None:
    _cleanup_legacy_scheduled_task()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass


PAD_X = 24
ACCENT = "#76B900"   # NVIDIA green
GREEN_DIM = "#5b8a00"
GREY = "#888"
CARD_BG = "#1f1f23"
OLED_BG = "#0a0a0a"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GPU OLED Monitor")
        self.geometry("460x720")
        self.minsize(460, 520)

        self.config_data = load_config()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Enumerate GPUs and pick a backend for the preview.
        self.gpus = list_gpus()
        self.gpu_options = ["Auto"] + [f"{g['name']}  ({g['id']})" for g in self.gpus]
        self._gpu_id_for_label = {"Auto": "auto",
                                  **{f"{g['name']}  ({g['id']})": g["id"] for g in self.gpus}}
        self._label_for_gpu_id = {v: k for k, v in self._gpu_id_for_label.items()}

        self.preview_backend = self._make_backend(self.config_data.get("gpu_id", "auto"))

        self.label_to_key = {s.label: s.key for s in STATS.values()}
        self.key_to_label = {s.key: s.label for s in STATS.values()}
        labels = list(self.label_to_key.keys())

        # --- Pinned bottom area (credit + Controls card always visible) ---
        # Pack order: credit first, controls above it, then scroll fills the rest.
        ctk.CTkLabel(self, text="made by jordanfromnz",
                     font=ctk.CTkFont(size=10), text_color="#555").pack(side="bottom", pady=(0, 8))

        controls = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=10)
        controls.pack(side="bottom", fill="x", padx=PAD_X, pady=(8, 4))

        self.run_btn = ctk.CTkButton(controls, text="Start monitor", command=self._toggle_running,
                                     fg_color=ACCENT, hover_color=GREEN_DIM, text_color="#000")
        self.run_btn.pack(fill="x", padx=18, pady=(14, 8))

        self.autostart_var = ctk.BooleanVar(value=is_autostart_enabled())
        ctk.CTkSwitch(controls, text="Run at login", variable=self.autostart_var,
                      command=self._toggle_autostart,
                      progress_color=ACCENT).pack(padx=18, pady=(0, 8), anchor="w")

        self.status = ctk.CTkLabel(controls, text="", anchor="w")
        self.status.pack(fill="x", padx=18, pady=(0, 14))

        # --- Scrollable area for everything else ---
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(side="top", fill="both", expand=True)

        # --- Header ---
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=PAD_X - 6, pady=(8, 12))
        ctk.CTkLabel(header, text="GPU OLED Monitor",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Apex Pro Gen3  ·  GameSense",
                     font=ctk.CTkFont(size=12), text_color=GREY).pack(anchor="w")

        # --- GPU source ---
        current_gpu_label = self._label_for_gpu_id.get(
            self.config_data.get("gpu_id", "auto"), "Auto")
        gpu_card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=10)
        gpu_card.pack(fill="x", padx=PAD_X - 6, pady=(0, 12))
        ctk.CTkLabel(gpu_card, text="GPU SOURCE",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=ACCENT).pack(padx=18, pady=(14, 4), anchor="w")
        self.gpu_var = ctk.StringVar(value=current_gpu_label)
        ctk.CTkOptionMenu(gpu_card, values=self.gpu_options, variable=self.gpu_var,
                          command=self._on_gpu_change,
                          button_color=ACCENT, button_hover_color=GREEN_DIM,
                          ).pack(fill="x", padx=18, pady=(0, 14))

        # --- OLED preview ---
        preview = ctk.CTkFrame(scroll, fg_color=OLED_BG, corner_radius=10, height=110,
                               border_width=1, border_color="#2a2a2e")
        preview.pack(fill="x", padx=PAD_X - 6, pady=(0, 16))
        preview.pack_propagate(False)
        self.preview_label = ctk.CTkLabel(
            preview, text="—", justify="left", text_color="#FFFFFF",
            font=ctk.CTkFont(family="Consolas", size=22, weight="bold"),
        )
        self.preview_label.pack(expand=True)

        # --- Settings card ---
        settings = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=10)
        settings.pack(fill="x", padx=PAD_X - 6, pady=(0, 12))

        self._section(settings, "Page 1")
        self.line1_var = self._dropdown(settings, "Top line", self.config_data["line1"], labels)
        self.line2_var = self._dropdown(settings, "Bottom line", self.config_data["line2"], labels,
                                        bottom_pad=10)

        self.cycle_var = ctk.BooleanVar(value=self.config_data["cycle_enabled"])
        ctk.CTkSwitch(settings, text="Cycle through 2 pages",
                      variable=self.cycle_var, command=self._on_cycle_toggle,
                      progress_color=ACCENT).pack(padx=18, pady=(0, 6), anchor="w")

        self._section(settings, "Page 2")
        self.alt1_var, self.alt1_menu = self._dropdown(settings, "Top line",
                                                       self.config_data["alt_line1"], labels,
                                                       return_menu=True)
        self.alt2_var, self.alt2_menu = self._dropdown(settings, "Bottom line",
                                                       self.config_data["alt_line2"], labels,
                                                       return_menu=True, bottom_pad=8)

        interval_row = ctk.CTkFrame(settings, fg_color="transparent")
        interval_row.pack(fill="x", padx=18, pady=(0, 16))
        ctk.CTkLabel(interval_row, text="Cycle every").pack(side="left")
        self.interval_var = ctk.StringVar(value=str(self.config_data["cycle_seconds"]))
        self.interval_entry = ctk.CTkEntry(interval_row, width=50, textvariable=self.interval_var)
        self.interval_entry.pack(side="left", padx=(8, 4))
        self.interval_entry.bind("<FocusOut>", lambda _: self._on_change())
        self.interval_entry.bind("<Return>", lambda _: self._on_change())
        ctk.CTkLabel(interval_row, text="seconds").pack(side="left")

        # --- Warnings card ---
        warn_card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=10)
        warn_card.pack(fill="x", padx=PAD_X - 6, pady=(0, 12))
        self._section(warn_card, "Warnings")

        # Temp
        self.warn_var = ctk.BooleanVar(value=self.config_data["temp_warning_enabled"])
        ctk.CTkSwitch(warn_card, text="GPU temp warning",
                      variable=self.warn_var, command=self._on_change,
                      progress_color=ACCENT).pack(padx=18, pady=(0, 4), anchor="w")
        thresh_row = ctk.CTkFrame(warn_card, fg_color="transparent")
        thresh_row.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(thresh_row, text="Threshold").pack(side="left")
        self.thresh_var = ctk.StringVar(value=str(self.config_data["temp_warning_threshold"]))
        self.thresh_entry = ctk.CTkEntry(thresh_row, width=50, textvariable=self.thresh_var)
        self.thresh_entry.pack(side="left", padx=(8, 4))
        self.thresh_entry.bind("<FocusOut>", lambda _: self._on_change())
        self.thresh_entry.bind("<Return>", lambda _: self._on_change())
        ctk.CTkLabel(thresh_row, text="°C").pack(side="left")

        # Power
        self.power_warn_var = ctk.BooleanVar(value=self.config_data["power_warning_enabled"])
        ctk.CTkSwitch(warn_card, text="GPU power-draw warning",
                      variable=self.power_warn_var, command=self._on_change,
                      progress_color=ACCENT).pack(padx=18, pady=(0, 4), anchor="w")
        power_row = ctk.CTkFrame(warn_card, fg_color="transparent")
        power_row.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkLabel(power_row, text="Threshold").pack(side="left")
        self.power_thresh_var = ctk.StringVar(value=str(self.config_data["power_warning_threshold"]))
        self.power_thresh_entry = ctk.CTkEntry(power_row, width=60, textvariable=self.power_thresh_var)
        self.power_thresh_entry.pack(side="left", padx=(8, 4))
        self.power_thresh_entry.bind("<FocusOut>", lambda _: self._on_change())
        self.power_thresh_entry.bind("<Return>", lambda _: self._on_change())
        ctk.CTkLabel(power_row, text="W").pack(side="left")

        self._apply_cycle_state()
        self._refresh_status()
        self.after(1000, self._tick)

    # ---- builders ----

    def _section(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=ACCENT).pack(padx=18, pady=(14, 4), anchor="w")

    def _dropdown(self, parent, label: str, value_key: str, labels: list[str],
                  bottom_pad: int = 4, return_menu: bool = False):
        ctk.CTkLabel(parent, text=label, anchor="w",
                     text_color=GREY, font=ctk.CTkFont(size=11)).pack(fill="x", padx=18)
        var = ctk.StringVar(value=self.key_to_label.get(value_key, labels[0]))
        menu = ctk.CTkOptionMenu(parent, values=labels, variable=var,
                                 command=lambda _: self._on_change(),
                                 button_color=ACCENT, button_hover_color=GREEN_DIM)
        menu.pack(fill="x", padx=18, pady=(2, bottom_pad))
        return (var, menu) if return_menu else var

    # ---- behavior ----

    def _make_backend(self, gpu_id: str):
        try:
            return get_backend(gpu_id)
        except Exception:
            return None

    def _on_close(self) -> None:
        if self.preview_backend is not None:
            try:
                self.preview_backend.shutdown()
            except Exception:
                pass
        self.destroy()

    def _on_gpu_change(self, label: str) -> None:
        new_id = self._gpu_id_for_label.get(label, "auto")
        if new_id == self.config_data.get("gpu_id"):
            return
        if self.preview_backend is not None:
            try: self.preview_backend.shutdown()
            except Exception: pass
        self.preview_backend = self._make_backend(new_id)
        self._on_change()

    def _on_change(self) -> None:
        try:
            seconds = max(1, int(self.interval_var.get()))
        except ValueError:
            seconds = self.config_data.get("cycle_seconds", 4)
            self.interval_var.set(str(seconds))
        try:
            threshold = max(30, min(120, int(self.thresh_var.get())))
        except ValueError:
            threshold = self.config_data.get("temp_warning_threshold", 80)
            self.thresh_var.set(str(threshold))
        try:
            power_threshold = max(50, min(2000, int(self.power_thresh_var.get())))
        except ValueError:
            power_threshold = self.config_data.get("power_warning_threshold", 600)
            self.power_thresh_var.set(str(power_threshold))
        # Re-read from disk first so we don't overwrite overlay_x/y the daemon
        # may have just persisted while the user was dragging the warning popup.
        cfg = {
            **load_config(),
            "line1": self.label_to_key[self.line1_var.get()],
            "line2": self.label_to_key[self.line2_var.get()],
            "alt_line1": self.label_to_key[self.alt1_var.get()],
            "alt_line2": self.label_to_key[self.alt2_var.get()],
            "cycle_enabled": self.cycle_var.get(),
            "cycle_seconds": seconds,
            "gpu_id": self._gpu_id_for_label.get(self.gpu_var.get(), "auto"),
            "temp_warning_enabled": self.warn_var.get(),
            "temp_warning_threshold": threshold,
            "power_warning_enabled": self.power_warn_var.get(),
            "power_warning_threshold": power_threshold,
        }
        save_config(cfg)
        self.config_data = cfg

    def _on_cycle_toggle(self) -> None:
        self._apply_cycle_state()
        self._on_change()

    def _apply_cycle_state(self) -> None:
        state = "normal" if self.cycle_var.get() else "disabled"
        self.alt1_menu.configure(state=state)
        self.alt2_menu.configure(state=state)
        self.interval_entry.configure(state=state)

    def _toggle_running(self) -> None:
        if is_running():
            stop_monitor()
        else:
            start_monitor()
        self.after(400, self._refresh_status)

    def _toggle_autostart(self) -> None:
        try:
            if self.autostart_var.get():
                install_autostart()
            else:
                uninstall_autostart()
        except Exception as e:
            try:
                self.status.configure(
                    text=f"Autostart: {type(e).__name__}: {e}", text_color="#e88")
            except Exception:
                pass
            try:
                self.autostart_var.set(is_autostart_enabled())
            except Exception:
                pass

    def _refresh_status(self) -> None:
        if is_running():
            self.run_btn.configure(text="Stop monitor")
            self.status.configure(text="●  Running", text_color=ACCENT)
        else:
            self.run_btn.configure(text="Start monitor")
            self.status.configure(text="○  Stopped", text_color=GREY)

    def _update_preview(self) -> None:
        if self.preview_backend is None:
            self.preview_label.configure(text="(no GPU backend available)",
                                         text_color="#666", font=ctk.CTkFont(size=12))
            return
        try:
            cfg = load_config()
            key1, key2 = current_lines(cfg)
            l1 = render_line(key1, self.preview_backend)
            l2 = render_line(key2, self.preview_backend)
            self.preview_label.configure(text=f"{l1}\n{l2}")
        except Exception as e:
            self.preview_label.configure(text=f"(preview error: {e})",
                                         text_color="#666", font=ctk.CTkFont(size=12))

    def _tick(self) -> None:
        try:
            self._update_preview()
            self._refresh_status()
        except Exception:
            # report_callback_exception in main.py logs uncaught GUI errors,
            # but we want the after-chain to keep ticking regardless.
            import traceback
            traceback.print_exc()
        self.after(1000, self._tick)


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()

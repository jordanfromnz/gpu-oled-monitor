"""Configuration GUI for the GPU OLED monitor."""

import json
import subprocess
import sys
from pathlib import Path

import customtkinter as ctk
import psutil

from gpu_backend import get_backend, list_gpus
from stats import STATS, current_lines, render_line


FROZEN = getattr(sys, "frozen", False)
PROJECT_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"
SCRIPT_FILE = PROJECT_DIR / "gpu_oled.py"
PID_FILE = PROJECT_DIR / "gpu_oled.pid"
TASK_NAME = "GPU OLED Monitor"

DEFAULT_CONFIG = {
    "line1": "gpu_temp",
    "line2": "gpu_power",
    "alt_line1": "gpu_util",
    "alt_line2": "mem_used",
    "cycle_enabled": False,
    "cycle_seconds": 4,
    "gpu_id": "auto",
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


def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        return psutil.pid_exists(pid)
    except (ValueError, OSError):
        return False


def start_monitor() -> None:
    subprocess.Popen(
        daemon_command(),
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def stop_monitor() -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=3)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired, ValueError):
        pass
    PID_FILE.unlink(missing_ok=True)


def is_autostart_enabled() -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.returncode == 0


def install_autostart() -> None:
    cmd = daemon_command()
    tr = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    subprocess.run([
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", tr,
        "/sc", "onlogon",
        "/rl", "limited",
        "/f",
    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def uninstall_autostart() -> None:
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )


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
        self.geometry("420x880")
        self.resizable(False, False)

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

        # --- Credit (packed first so side=bottom reserves its slot) ---
        ctk.CTkLabel(self, text="made by jordanfromnz",
                     font=ctk.CTkFont(size=10), text_color="#555").pack(side="bottom", pady=(0, 8))

        # --- Header ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PAD_X, pady=(18, 12))
        ctk.CTkLabel(header, text="GPU OLED Monitor",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Apex Pro Gen3  ·  GameSense",
                     font=ctk.CTkFont(size=12), text_color=GREY).pack(anchor="w")

        # --- GPU source ---
        current_gpu_label = self._label_for_gpu_id.get(
            self.config_data.get("gpu_id", "auto"), "Auto")
        gpu_card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=10)
        gpu_card.pack(fill="x", padx=PAD_X, pady=(0, 12))
        ctk.CTkLabel(gpu_card, text="GPU SOURCE",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=ACCENT).pack(padx=18, pady=(14, 4), anchor="w")
        self.gpu_var = ctk.StringVar(value=current_gpu_label)
        ctk.CTkOptionMenu(gpu_card, values=self.gpu_options, variable=self.gpu_var,
                          command=self._on_gpu_change,
                          button_color=ACCENT, button_hover_color=GREEN_DIM,
                          ).pack(fill="x", padx=18, pady=(0, 14))

        # --- OLED preview ---
        preview = ctk.CTkFrame(self, fg_color=OLED_BG, corner_radius=10, height=110,
                               border_width=1, border_color="#2a2a2e")
        preview.pack(fill="x", padx=PAD_X, pady=(0, 16))
        preview.pack_propagate(False)
        self.preview_label = ctk.CTkLabel(
            preview, text="—", justify="left", text_color="#FFFFFF",
            font=ctk.CTkFont(family="Consolas", size=22, weight="bold"),
        )
        self.preview_label.pack(expand=True)

        # --- Settings card ---
        settings = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=10)
        settings.pack(fill="x", padx=PAD_X, pady=(0, 12))

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

        # --- Controls card ---
        controls = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=10)
        controls.pack(fill="x", padx=PAD_X, pady=(0, 12))

        self.run_btn = ctk.CTkButton(controls, text="Start monitor", command=self._toggle_running,
                                     fg_color=ACCENT, hover_color=GREEN_DIM, text_color="#000")
        self.run_btn.pack(fill="x", padx=18, pady=(16, 10))

        self.autostart_var = ctk.BooleanVar(value=is_autostart_enabled())
        ctk.CTkSwitch(controls, text="Run at login", variable=self.autostart_var,
                      command=self._toggle_autostart,
                      progress_color=ACCENT).pack(padx=18, pady=(0, 12), anchor="w")

        self.status = ctk.CTkLabel(controls, text="", anchor="w")
        self.status.pack(fill="x", padx=18, pady=(0, 16))

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
        cfg = {
            "line1": self.label_to_key[self.line1_var.get()],
            "line2": self.label_to_key[self.line2_var.get()],
            "alt_line1": self.label_to_key[self.alt1_var.get()],
            "alt_line2": self.label_to_key[self.alt2_var.get()],
            "cycle_enabled": self.cycle_var.get(),
            "cycle_seconds": seconds,
            "gpu_id": self._gpu_id_for_label.get(self.gpu_var.get(), "auto"),
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
        except subprocess.CalledProcessError as e:
            self.status.configure(text=f"Autostart change failed: {e}", text_color="#e88")
            self.autostart_var.set(is_autostart_enabled())

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
        self._update_preview()
        self._refresh_status()
        self.after(1000, self._tick)


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()

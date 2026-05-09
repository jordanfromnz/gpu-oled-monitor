"""GPU stats on the SteelSeries Apex Pro Gen3 OLED.

Replicates the GPU stats from NVIDIA's in-game overlay (temp, power draw, etc.)
on the keyboard's built-in OLED via the SteelSeries GameSense SDK. The two lines
shown are configured in config.json (edit via config_app.py).
"""

import atexit
import json
import logging
import os
import sys
from pathlib import Path

import requests

from gpu_backend import get_backend
from stats import current_lines, render_line


PROJECT_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"
LOG_FILE = PROJECT_DIR / "gpu_oled.log"
PID_FILE = PROJECT_DIR / "gpu_oled.pid"

GAME = "GPU_MONITOR"
EVENT = "GPU_STATS"
DEVELOPER = "jordanfromnz"
DISPLAY_NAME = "NVIDIA-style GPU Overlay"
ICON_COLOR_ID = 3
SCREEN_ICON_ID = 26

POLL_SECONDS = 1.0
HEARTBEAT_EVERY = 10  # ticks
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


logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("gpu_oled")


def gamesense_address() -> str:
    core_props = Path(os.environ["PROGRAMDATA"]) / "SteelSeries" / "SteelSeries Engine 3" / "coreProps.json"
    return json.loads(core_props.read_text())["address"]


def post(base: str, path: str, payload: dict, timeout: float = 5.0) -> None:
    r = requests.post(f"http://{base}{path}", json=payload, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status_code}: {r.text}")


def register(base: str) -> None:
    log.info("Registering game metadata")
    post(base, "/game_metadata", {
        "game": GAME,
        "game_display_name": DISPLAY_NAME,
        "developer": DEVELOPER,
        "icon_color_id": ICON_COLOR_ID,
    })

    log.info("Binding text-line event handler")
    post(base, "/bind_game_event", {
        "game": GAME,
        "event": EVENT,
        "value_optional": True,
        "handlers": [{
            "device-type": "screened-128x40",
            "mode": "screen",
            "zone": "one",
            "datas": [{
                "lines": [
                    {"has-text": True, "context-frame-key": "line1"},
                    {"has-text": True, "context-frame-key": "line2"},
                ],
            }],
        }],
    }, timeout=10.0)


def push(base: str, line1: str, line2: str) -> None:
    post(base, "/game_event", {
        "game": GAME,
        "event": EVENT,
        "data": {"value": 0, "frame": {"line1": line1, "line2": line2}},
    })


def heartbeat(base: str) -> None:
    post(base, "/game_heartbeat", {"game": GAME})


def connect() -> str:
    base = gamesense_address()
    log.info(f"GameSense at {base}")
    register(base)
    return base


def load_config() -> dict:
    try:
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def write_pid_file() -> None:
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))


def _make_position_saver(key_x: str, key_y: str):
    """Returns a callback that persists (x, y) to config under the given keys."""
    def save(x: int, y: int) -> None:
        try:
            cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        except json.JSONDecodeError:
            cfg = {}
        cfg[key_x] = x
        cfg[key_y] = y
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    return save


def main() -> None:
    write_pid_file()
    log.info("Starting GPU OLED monitor")

    config = load_config()
    backend = get_backend(config.get("gpu_id", "auto"))
    log.info(f"Monitoring: {backend.name}")

    base = [connect()]   # mutable cell so the closure can rebind on reconnect
    tick = [0]

    # Hidden tk root — needed for after() scheduling and as the overlay's parent.
    import customtkinter as ctk
    from overlay import WarningOverlay
    root = ctk.CTk()
    root.withdraw()

    # Two independent warning overlays: temp and power.
    overlays: dict[str, WarningOverlay | None] = {"temp": None, "power": None}

    OVERLAY_SPECS = {
        "temp": {
            "icon": "⚠",
            "message": "Temps exceeding configured limits",
            "pos_x_key": "overlay_x",
            "pos_y_key": "overlay_y",
            "default_pos": (100, 100),
        },
        "power": {
            "icon": "⚡",
            "message": "Power draw exceeding configured limits",
            "pos_x_key": "power_overlay_x",
            "pos_y_key": "power_overlay_y",
            "default_pos": (100, 210),
        },
    }

    def hide_overlay(kind: str) -> None:
        if overlays[kind] is not None:
            try: overlays[kind].destroy()
            except Exception: pass
            overlays[kind] = None

    def show_or_update_overlay(kind: str, name: str, value_str: str, cfg: dict) -> None:
        spec = OVERLAY_SPECS[kind]
        if overlays[kind] is None:
            o = WarningOverlay(
                root, icon=spec["icon"], message=spec["message"],
                on_position_change=_make_position_saver(spec["pos_x_key"], spec["pos_y_key"]),
            )
            x = int(cfg.get(spec["pos_x_key"], spec["default_pos"][0]))
            y = int(cfg.get(spec["pos_y_key"], spec["default_pos"][1]))
            o.position_at(x, y)
            overlays[kind] = o
        overlays[kind].update_content(name, value_str)

    def check_threshold(kind: str, cfg: dict, enabled_key: str, threshold_key: str,
                        default_threshold, value, format_value) -> None:
        if not cfg.get(enabled_key):
            hide_overlay(kind)
            return
        if value is None:
            return
        threshold = float(cfg.get(threshold_key, default_threshold))
        if value >= threshold:
            show_or_update_overlay(kind, backend.name, format_value(value), cfg)
        elif value < threshold - 2:
            hide_overlay(kind)

    def step() -> None:
        try:
            cfg = load_config()

            # OLED push
            try:
                key1, key2 = current_lines(cfg)
                push(base[0], render_line(key1, backend), render_line(key2, backend))
                if tick[0] % HEARTBEAT_EVERY == 0:
                    heartbeat(base[0])
                tick[0] += 1
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    RuntimeError) as e:
                log.warning(f"GameSense unreachable ({type(e).__name__}); reconnecting")
                try:
                    base[0] = connect()
                except Exception as e2:
                    log.warning(f"Reconnect failed: {e2}")

            check_threshold("temp", cfg,
                            "temp_warning_enabled", "temp_warning_threshold", 80,
                            backend.temperature_c(),
                            lambda v: f"{int(v)}°C")
            check_threshold("power", cfg,
                            "power_warning_enabled", "power_warning_threshold", 600,
                            backend.power_w(),
                            lambda v: f"{int(round(v))}W")
        except Exception:
            log.exception("Unexpected error in tick loop; continuing")
        root.after(int(POLL_SECONDS * 1000), step)

    root.after(0, step)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        log.info("Stopped via KeyboardInterrupt")
    finally:
        for k in list(overlays.keys()):
            hide_overlay(k)
        try: root.destroy()
        except Exception: pass
        backend.shutdown()


if __name__ == "__main__":
    main()

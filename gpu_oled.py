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
import time
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


def main() -> None:
    write_pid_file()
    log.info("Starting GPU OLED monitor")

    config = load_config()
    backend = get_backend(config.get("gpu_id", "auto"))
    log.info(f"Monitoring: {backend.name}")

    base = connect()
    tick = 0
    try:
        while True:
            try:
                config = load_config()
                key1, key2 = current_lines(config)
                push(base, render_line(key1, backend), render_line(key2, backend))

                if tick % HEARTBEAT_EVERY == 0:
                    heartbeat(base)
                tick += 1
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    RuntimeError) as e:
                log.warning(f"GameSense unreachable ({type(e).__name__}); reconnecting in 3s")
                time.sleep(3)
                try:
                    base = connect()
                except Exception as e2:
                    log.warning(f"Reconnect failed: {e2}")
                    continue
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log.info("Stopped via KeyboardInterrupt")
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()

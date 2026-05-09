"""Available stats that can be displayed on the OLED."""

import time
from dataclasses import dataclass
from typing import Callable

import psutil

from gpu_backend import GpuBackend

# Prime so the first reading is meaningful instead of 0.0.
psutil.cpu_percent(interval=None)


@dataclass(frozen=True)
class Stat:
    key: str
    label: str        # shown in the GUI dropdown
    prefix: str       # rendered before the value on the OLED (incl. inline icon)
    fn: Callable[[GpuBackend], str]


def _na(v) -> str:
    return "N/A" if v is None else str(v)


def _temp(b: GpuBackend) -> str:
    t = b.temperature_c()
    return f"{t}{chr(176)}C" if t is not None else "N/A"


def _power(b: GpuBackend) -> str:
    p = b.power_w()
    return f"{p:.1f}W" if p is not None else "N/A"


def _gpu_util(b: GpuBackend) -> str:
    u = b.utilization_pct()
    return f"{u}%" if u is not None else "N/A"


def _mem_pct(b: GpuBackend) -> str:
    used = b.vram_used_bytes()
    total = b.vram_total_bytes()
    if used is None or total is None or total == 0:
        return "N/A"
    return f"{100 * used / total:.0f}%"


def _mem_used(b: GpuBackend) -> str:
    used = b.vram_used_bytes()
    return f"{used / (1024 ** 3):.1f}GB" if used is not None else "N/A"


def _fan(b: GpuBackend) -> str:
    f = b.fan_pct()
    return f"{f}%" if f is not None else "N/A"


def _core_clock(b: GpuBackend) -> str:
    c = b.core_clock_mhz()
    return f"{c}MHz" if c is not None else "N/A"


def _mem_clock(b: GpuBackend) -> str:
    c = b.mem_clock_mhz()
    return f"{c}MHz" if c is not None else "N/A"


def _cpu_util(_b: GpuBackend) -> str:
    return f"{psutil.cpu_percent(interval=None):.0f}%"


def _ram_pct(_b: GpuBackend) -> str:
    return f"{psutil.virtual_memory().percent:.0f}%"


def _ram_used(_b: GpuBackend) -> str:
    used_gb = psutil.virtual_memory().used / (1024 ** 3)
    return f"{used_gb:.1f}GB"


STATS: dict[str, Stat] = {
    s.key: s for s in [
        Stat("gpu_temp",   "GPU Temperature", "° GPU",  _temp),
        Stat("gpu_power",  "GPU Power Draw",  "⚡ PWR",  _power),
        Stat("gpu_util",   "GPU Usage",       "▓ GPU",  _gpu_util),
        Stat("mem_pct",    "VRAM Usage %",    "▤ VRAM", _mem_pct),
        Stat("mem_used",   "VRAM Used",       "▤ VRAM", _mem_used),
        Stat("fan",        "Fan Speed",       "⚙ FAN",  _fan),
        Stat("core_clock", "Core Clock",      "♫ CLK",  _core_clock),
        Stat("mem_clock",  "Memory Clock",    "♪ MEM",  _mem_clock),
        Stat("cpu_util",   "CPU Usage",       "▒ CPU",  _cpu_util),
        Stat("ram_pct",    "RAM Usage %",     "▥ RAM",  _ram_pct),
        Stat("ram_used",   "RAM Used",        "▥ RAM",  _ram_used),
    ]
}


def render_line(stat_key: str, backend: GpuBackend) -> str:
    """Format one line of OLED text for the given stat."""
    stat = STATS.get(stat_key, STATS["gpu_temp"])
    return f"{stat.prefix}  {stat.fn(backend)}"


def current_lines(config: dict) -> tuple[str, str]:
    """Pick which two stat keys to show right now based on cycle settings."""
    if config.get("cycle_enabled"):
        secs = max(1, int(config.get("cycle_seconds", 4)))
        if int(time.time() / secs) % 2 == 1:
            return config["alt_line1"], config["alt_line2"]
    return config["line1"], config["line2"]

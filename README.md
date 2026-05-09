# GPU OLED Monitor

Display live GPU stats on the SteelSeries Apex Pro Gen3 OLED — a tiny replacement for the on-keyboard stats app that SteelSeries pulled due to WinRing0 vulns. This utilizes existing stats, doesn't use WinRing0 and requires no other third party programs running. It also offers a convenient GUI for quick customisation.

Single `.exe`. No HWiNFO. No INI editing. Pick your stats, click run.

## Features

- Live GPU stats pushed to the keyboard's OLED via the SteelSeries GameSense SDK
- Inline icons per stat (`° GPU 32°C`, `⚡ PWR 65.2W`, …)
- Two-page cycling — show up to four stats, alternating between pages
- Clean configuration GUI with a live OLED preview
- **Threshold warnings** — frameless always-on-top desktop popups when GPU temperature or power draw exceeds your configured limits (default 80°C / 600W). Position is remembered.
- One-click "Run at login" (registers under the user-scope Windows autostart key — no admin, no scheduled task)
- NVIDIA (NVML) and AMD (ADL / ADL2 PMLogData) support
- Resilient to SteelSeries Engine restarts (port rotation handled automatically)

## Available stats

**GPU** — temperature, power draw, usage %, VRAM used, VRAM %, fan %, core clock, memory clock
**System** — CPU usage %, RAM usage %, RAM used

CPU temperature isn't available for now — reading it would require integration with HWInfo Stats. If you need CPU temp or other stats not available from nvml, [HWiNFO-SteelSeries](https://github.com/ForbesGRyan/HWiNFO-SteelSeries) covers that path well. This was primarily built as a GPU monitoring display for temp and power draw.

## Requirements

- Windows 10 / 11
- [SteelSeries GG](https://steelseries.com/gg) installed and running
- A SteelSeries keyboard with a 128x40 OLED (built and tested on Apex Pro Gen3; other Apex Pro / TKL models likely work)
- An NVIDIA or AMD GPU with current drivers

## Quick start

1. Download `GPU-OLED-Monitor.exe` from the [Releases](../../releases) page
2. Put it anywhere — `config.json` and logs get created next to it
3. Double-click to open the config GUI
4. Pick the stats for line 1, line 2 (and optionally cycling Page 2)
5. Click **Start monitor**, optionally toggle **Run at login**

## Configuration

The GUI saves to `config.json` next to the executable. You can edit it by hand if you prefer:

```json
{
  "line1": "gpu_temp",
  "line2": "gpu_power",
  "alt_line1": "gpu_util",
  "alt_line2": "ram_pct",
  "cycle_enabled": true,
  "cycle_seconds": 4,
  "gpu_id": "auto",

  "temp_warning_enabled": false,
  "temp_warning_threshold": 80,
  "overlay_x": 100,
  "overlay_y": 100,

  "power_warning_enabled": false,
  "power_warning_threshold": 600,
  "power_overlay_x": 100,
  "power_overlay_y": 210
}
```

`gpu_id` is `"auto"` by default, or `"nvidia:0"` / `"amd:1"` to pin a specific card.

## Threshold warnings

When enabled, a frameless always-on-top popup appears whenever the relevant metric exceeds its threshold, and disappears once it drops a couple of degrees/watts below (hysteresis to avoid flicker). Each popup is independent and draggable — its position is saved to `config.json` and restored on the next launch.

- **Temp** — defaults to **80 °C**. Useful as an early-warning if airflow gets blocked or fan curves stop responding.
- **Power draw** — defaults to **600 W**, the rated limit of the 12VHPWR connector. Particularly relevant on cards like the RTX 5090 that can transiently spike past it; pairing the warning with the OLED makes it visible whether your eyes are on the keyboard or the desktop.

Both warnings only fire while the daemon is running — same lifecycle as the OLED stat push. Toggle them on/off in the GUI's *Warnings* card.

## AMD support

The AMD backend is implemented against AMD's published ADL SDK but **untested without an AMD card**. The flow per sensor:

1. Try ADL2 `PMLogData` (modern, covers RDNA1+)
2. Fall back to legacy Overdrive 5 / 6 calls (Polaris/Vega era)
3. If neither responds, the GUI shows `N/A` for that stat and continues

If you have an AMD GPU and a sensor reads wrong, [open an issue](../../issues) with your GPU model and which value's off — easy to fix once we know what your card reports.

## Building from source

```bash
git clone https://github.com/<your-username>/gpu-oled-monitor
cd gpu-oled-monitor
python -m pip install -r requirements.txt
python main.py            # GUI
python main.py --daemon   # daemon (what the GUI launches)
```

Bundle a single `.exe`:

```bash
python -m PyInstaller --noconfirm --noconsole --onefile --name "GPU-OLED-Monitor" --collect-data customtkinter main.py
```

## Project layout

| File | Purpose |
|------|---------|
| `main.py` | Entry point: dispatches to GUI or daemon based on `--daemon` flag |
| `config_app.py` | customtkinter GUI |
| `gpu_oled.py` | Daemon that polls stats, pushes to GameSense, and hosts warning overlays |
| `gpu_backend.py` | NVIDIA + AMD vendor abstraction |
| `overlay.py` | Frameless always-on-top warning popup |
| `stats.py` | Available stat formatters and the inline-icon palette |
| `config.json` | User config (lines, cycle, gpu_id, warning thresholds & positions) |

## Credits

- SteelSeries — [GameSense SDK](https://github.com/SteelSeries/gamesense-sdk)
- NVIDIA — `pynvml` / NVML
- AMD — published ADL SDK headers
- [customtkinter](https://github.com/TomSchimansky/CustomTkinter), [psutil](https://github.com/giampaolo/psutil), [requests](https://github.com/psf/requests), [PyInstaller](https://pyinstaller.org)

## License

MIT — see [LICENSE](LICENSE).

made by jordanfromnz for all the people who bought a keyboard mainly for this purpose only to have the app go missing :D

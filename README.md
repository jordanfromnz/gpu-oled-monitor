# GPU OLED Monitor

Display live GPU stats on the SteelSeries Apex Pro Gen3 OLED — a tiny replacement for the on-keyboard stats app that SteelSeries pulled due to WinRing0 vulns. This utilizes existing stats, doesn't use WinRing0 and requires no other third party programs running. It also offers a convenient GUI for quick customisation.

Single `.exe`. No HWiNFO. No INI editing. Pick your stats, click run.

## Features

- Live GPU stats pushed to the keyboard's OLED via the SteelSeries GameSense SDK
- Inline icons per stat (`° GPU 32°C`, `⚡ PWR 65.2W`, …)
- Two-page cycling — show up to four stats, alternating between pages
- Clean configuration GUI with a live OLED preview
- One-click "Run at login" via Windows Task Scheduler
- NVIDIA (NVML) and AMD (ADL / ADL2 PMLogData) support
- Resilient to SteelSeries Engine restarts (port rotation handled automatically)

## Available stats

**GPU** — temperature, power draw, usage %, VRAM used, VRAM %, fan %, core clock, memory clock
**System** — CPU usage %, RAM usage %, RAM used

CPU temperature isn't included — reading it on Windows requires the `WinRing0` kernel driver (the same one that got SteelSeries' original stats app pulled). If you need CPU temp, [HWiNFO-SteelSeries](https://github.com/ForbesGRyan/HWiNFO-SteelSeries) covers that path well.

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
  "gpu_id": "auto"
}
```

`gpu_id` is `"auto"` by default, or `"nvidia:0"` / `"amd:1"` to pin a specific card.

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
| `gpu_oled.py` | Daemon that polls stats and pushes to GameSense |
| `gpu_backend.py` | NVIDIA + AMD vendor abstraction |
| `stats.py` | Available stat formatters and the inline-icon palette |
| `config.json` | User config (line selections, cycle settings, gpu_id) |

## Credits

- SteelSeries — [GameSense SDK](https://github.com/SteelSeries/gamesense-sdk)
- NVIDIA — `pynvml` / NVML
- AMD — published ADL SDK headers
- [customtkinter](https://github.com/TomSchimansky/CustomTkinter), [psutil](https://github.com/giampaolo/psutil), [requests](https://github.com/psf/requests), [PyInstaller](https://pyinstaller.org)

## License

MIT — see [LICENSE](LICENSE).

made by jordanfromnz

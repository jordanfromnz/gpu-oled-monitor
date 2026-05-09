"""GPU vendor abstraction.

NVIDIA: pynvml. AMD: ctypes against AMD's atiadlxx.dll (ADL/ADL2). Picked at
startup based on which DLL/library loads.

Each backend exposes the same set of read-only sensors used by stats.py.
Methods that aren't supported on a given vendor return None (the formatter
will render that as "N/A").
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from abc import ABC, abstractmethod
from typing import Optional


class GpuBackend(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def temperature_c(self) -> Optional[int]: ...

    @abstractmethod
    def power_w(self) -> Optional[float]: ...

    @abstractmethod
    def utilization_pct(self) -> Optional[int]: ...

    @abstractmethod
    def vram_used_bytes(self) -> Optional[int]: ...

    @abstractmethod
    def vram_total_bytes(self) -> Optional[int]: ...

    @abstractmethod
    def fan_pct(self) -> Optional[int]: ...

    @abstractmethod
    def core_clock_mhz(self) -> Optional[int]: ...

    @abstractmethod
    def mem_clock_mhz(self) -> Optional[int]: ...

    def shutdown(self) -> None: ...


# ----------------------------- NVIDIA ---------------------------------

class NvidiaBackend(GpuBackend):
    def __init__(self, index: int = 0) -> None:
        import pynvml
        self._nvml = pynvml
        pynvml.nvmlInit()
        self._handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        n = pynvml.nvmlDeviceGetName(self._handle)
        self._name = n.decode() if isinstance(n, bytes) else n

    @property
    def name(self) -> str:
        return self._name

    def _safe(self, fn, *args):
        try:
            return fn(*args)
        except self._nvml.NVMLError:
            return None

    def temperature_c(self) -> Optional[int]:
        return self._safe(self._nvml.nvmlDeviceGetTemperature,
                          self._handle, self._nvml.NVML_TEMPERATURE_GPU)

    def power_w(self) -> Optional[float]:
        v = self._safe(self._nvml.nvmlDeviceGetPowerUsage, self._handle)
        return v / 1000.0 if v is not None else None

    def utilization_pct(self) -> Optional[int]:
        v = self._safe(self._nvml.nvmlDeviceGetUtilizationRates, self._handle)
        return v.gpu if v is not None else None

    def vram_used_bytes(self) -> Optional[int]:
        v = self._safe(self._nvml.nvmlDeviceGetMemoryInfo, self._handle)
        return v.used if v is not None else None

    def vram_total_bytes(self) -> Optional[int]:
        v = self._safe(self._nvml.nvmlDeviceGetMemoryInfo, self._handle)
        return v.total if v is not None else None

    def fan_pct(self) -> Optional[int]:
        return self._safe(self._nvml.nvmlDeviceGetFanSpeed, self._handle)

    def core_clock_mhz(self) -> Optional[int]:
        return self._safe(self._nvml.nvmlDeviceGetClockInfo,
                          self._handle, self._nvml.NVML_CLOCK_GRAPHICS)

    def mem_clock_mhz(self) -> Optional[int]:
        return self._safe(self._nvml.nvmlDeviceGetClockInfo,
                          self._handle, self._nvml.NVML_CLOCK_MEM)

    def shutdown(self) -> None:
        try:
            self._nvml.nvmlShutdown()
        except self._nvml.NVMLError:
            pass


# ------------------------------- AMD ----------------------------------
# AMD ADL/ADL2 reference: AMD Display Library SDK
#   https://gpuopen.com/adl/
# We use the legacy ADL surface (atiadlxx.dll) because it's been stable for
# 10+ years and works on every Adrenalin driver. Newer ADLX is C++/COM and
# has no first-class Python binding.

ADL_OK = 0
ADL_MAX_PATH = 256

# Memory allocator ADL hands back to us; we just allocate and let Python free
# it when the bytearray goes out of scope (ADL's lifetime is shorter than ours).
_alloc_buffers: list[ctypes.Array] = []


@ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)
def _adl_alloc(size: int) -> int:
    buf = (ctypes.c_byte * size)()
    _alloc_buffers.append(buf)
    return ctypes.addressof(buf)


class _AdapterInfo(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iAdapterIndex", ctypes.c_int),
        ("strUDID", ctypes.c_char * ADL_MAX_PATH),
        ("iBusNumber", ctypes.c_int),
        ("iDeviceNumber", ctypes.c_int),
        ("iFunctionNumber", ctypes.c_int),
        ("iVendorID", ctypes.c_int),
        ("strAdapterName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("iPresent", ctypes.c_int),
        ("iExist", ctypes.c_int),
        ("strDriverPath", ctypes.c_char * ADL_MAX_PATH),
        ("strDriverPathExt", ctypes.c_char * ADL_MAX_PATH),
        ("strPNPString", ctypes.c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", ctypes.c_int),
    ]


class _PMActivity(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iEngineClock", ctypes.c_int),    # 10 KHz units
        ("iMemoryClock", ctypes.c_int),    # 10 KHz units
        ("iVddc", ctypes.c_int),           # millivolts
        ("iActivityPercent", ctypes.c_int),
        ("iCurrentPerformanceLevel", ctypes.c_int),
        ("iCurrentBusSpeed", ctypes.c_int),
        ("iCurrentBusLanes", ctypes.c_int),
        ("iMaximumBusLanes", ctypes.c_int),
        ("iReserved", ctypes.c_int),
    ]


class _FanSpeedValue(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iSpeedType", ctypes.c_int),       # 1 = RPM, 2 = percent
        ("iFanSpeed", ctypes.c_int),
        ("iFlags", ctypes.c_int),
    ]


ADL_DL_FANCTRL_SPEED_TYPE_PERCENT = 2

# ADL2 PMLogData — modern sensor API (RDNA1+). Subset of sensor IDs we query;
# full list is in AMD's adl_defines.h.
ADL_PMLOG_MAX_SENSORS = 256
ADL_PMLOG_CLK_GFXCLK = 0
ADL_PMLOG_CLK_MEMCLK = 1
ADL_PMLOG_TEMPERATURE_EDGE = 7
ADL_PMLOG_FAN_PERCENTAGE = 14
ADL_PMLOG_INFO_ACTIVITY_GFX = 18
ADL_PMLOG_ASIC_POWER = 22
ADL_PMLOG_TEMPERATURE_HOTSPOT = 26


class _ADLSensor(ctypes.Structure):
    _fields_ = [("supported", ctypes.c_int), ("value", ctypes.c_int)]


class _ADLPMLogData(ctypes.Structure):
    _fields_ = [
        ("ulSize", ctypes.c_int),
        ("ulVersion", ctypes.c_int),
        ("sensors", _ADLSensor * ADL_PMLOG_MAX_SENSORS),
    ]


class AmdBackend(GpuBackend):
    def __init__(self, adapter_index: Optional[int] = None) -> None:
        try:
            self._adl = ctypes.WinDLL("atiadlxx.dll")
        except OSError as e:
            raise RuntimeError("atiadlxx.dll not found — AMD driver missing?") from e

        # Init: ADL_Main_Control_Create(ADL_MAIN_MEMORY_ALLOC, 1)
        create = self._adl.ADL_Main_Control_Create
        create.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int), ctypes.c_int]
        create.restype = ctypes.c_int
        if create(_adl_alloc, 1) != ADL_OK:
            raise RuntimeError("ADL_Main_Control_Create failed")

        # Find first present adapter.
        num = ctypes.c_int(0)
        get_n = self._adl.ADL_Adapter_NumberOfAdapters_Get
        get_n.argtypes = [ctypes.POINTER(ctypes.c_int)]
        get_n.restype = ctypes.c_int
        if get_n(ctypes.byref(num)) != ADL_OK or num.value <= 0:
            raise RuntimeError("No AMD adapters present")

        infos = (_AdapterInfo * num.value)()
        get_info = self._adl.ADL_Adapter_AdapterInfo_Get
        get_info.argtypes = [ctypes.POINTER(_AdapterInfo), ctypes.c_int]
        get_info.restype = ctypes.c_int
        if get_info(infos, ctypes.sizeof(infos)) != ADL_OK:
            raise RuntimeError("ADL_Adapter_AdapterInfo_Get failed")

        candidates = [i for i in infos if i.iPresent and i.iVendorID == 0x1002]
        if not candidates:
            raise RuntimeError("No active AMD adapter found")
        if adapter_index is not None:
            match = next((c for c in candidates if c.iAdapterIndex == adapter_index), None)
            if match is None:
                raise RuntimeError(f"AMD adapter index {adapter_index} not present")
            chosen = match
        else:
            # Highest PCIe bus number — that's the discrete card on systems with
            # both an APU iGPU (low/internal bus) and a Radeon discrete card.
            chosen = max(candidates, key=lambda i: i.iBusNumber)
        self._idx = chosen.iAdapterIndex
        self._name = chosen.strAdapterName.decode("utf-8", errors="replace")

        # ADL2 context (modern API, used for PMLogData on RDNA+ cards).
        self._ctx = ctypes.c_void_p()
        try:
            create2 = self._adl.ADL2_Main_Control_Create
            create2.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int),
                                ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
            create2.restype = ctypes.c_int
            if create2(_adl_alloc, 1, ctypes.byref(self._ctx)) != ADL_OK:
                self._ctx = None
        except (AttributeError, OSError):
            self._ctx = None
        self._pmlog_disabled = False  # set true after a hard PMLogData failure

    @property
    def name(self) -> str:
        return self._name

    # ---- helpers ----
    def _call(self, fn_name: str, argtypes: list, *args) -> tuple[int, tuple]:
        fn = getattr(self._adl, fn_name)
        fn.argtypes = argtypes
        fn.restype = ctypes.c_int
        rc = fn(self._idx, *args)
        return rc, args

    def _pmlog(self) -> Optional[_ADLPMLogData]:
        """Modern sensor query — works on RDNA1+ cards. None if unsupported."""
        if self._ctx is None or self._pmlog_disabled:
            return None
        try:
            fn = self._adl.ADL2_New_QueryPMLogData_Get
        except AttributeError:
            self._pmlog_disabled = True
            return None
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_ADLPMLogData)]
        fn.restype = ctypes.c_int
        data = _ADLPMLogData()
        data.ulSize = ctypes.sizeof(_ADLPMLogData)
        if fn(self._ctx, self._idx, ctypes.byref(data)) != ADL_OK:
            self._pmlog_disabled = True
            return None
        return data

    @staticmethod
    def _pmlog_sensor(pm: Optional[_ADLPMLogData], *sensor_ids: int) -> Optional[int]:
        """First supported sensor value among the given IDs, else None."""
        if pm is None:
            return None
        for sid in sensor_ids:
            if 0 <= sid < ADL_PMLOG_MAX_SENSORS and pm.sensors[sid].supported:
                return pm.sensors[sid].value
        return None

    # ---- sensors ----
    def temperature_c(self) -> Optional[int]:
        v = self._pmlog_sensor(self._pmlog(),
                               ADL_PMLOG_TEMPERATURE_EDGE,
                               ADL_PMLOG_TEMPERATURE_HOTSPOT)
        if v is not None:
            return v
        # Legacy OD5: returns millidegrees C.
        temp = ctypes.c_int(0)
        rc, _ = self._call(
            "ADL_Overdrive5_Temperature_Get",
            [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
            0, ctypes.byref(temp),
        )
        return temp.value // 1000 if rc == ADL_OK else None

    def power_w(self) -> Optional[float]:
        v = self._pmlog_sensor(self._pmlog(), ADL_PMLOG_ASIC_POWER)
        if v is not None:
            return float(v)
        # Legacy OD6: returns power in fixed-point Q8 watts.
        try:
            power = ctypes.c_int(0)
            rc, _ = self._call(
                "ADL_Overdrive6_CurrentPower_Get",
                [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
                0, ctypes.byref(power),
            )
            return power.value / 256.0 if rc == ADL_OK else None
        except (AttributeError, OSError):
            return None

    def _activity(self) -> Optional[_PMActivity]:
        act = _PMActivity()
        act.iSize = ctypes.sizeof(_PMActivity)
        try:
            rc, _ = self._call(
                "ADL_Overdrive5_CurrentActivity_Get",
                [ctypes.c_int, ctypes.POINTER(_PMActivity)],
                ctypes.byref(act),
            )
            return act if rc == ADL_OK else None
        except (AttributeError, OSError):
            return None

    def utilization_pct(self) -> Optional[int]:
        v = self._pmlog_sensor(self._pmlog(), ADL_PMLOG_INFO_ACTIVITY_GFX)
        if v is not None:
            return v
        a = self._activity()
        return a.iActivityPercent if a else None

    def core_clock_mhz(self) -> Optional[int]:
        v = self._pmlog_sensor(self._pmlog(), ADL_PMLOG_CLK_GFXCLK)
        if v is not None:
            return v   # PMLogData reports MHz already
        a = self._activity()
        return a.iEngineClock // 100 if a else None  # OD5: 10 KHz -> MHz

    def mem_clock_mhz(self) -> Optional[int]:
        v = self._pmlog_sensor(self._pmlog(), ADL_PMLOG_CLK_MEMCLK)
        if v is not None:
            return v
        a = self._activity()
        return a.iMemoryClock // 100 if a else None

    def vram_used_bytes(self) -> Optional[int]:
        # ADL_Adapter_DedicatedVRAMUsage_Get(adapter, &usage_mb)
        used = ctypes.c_int(0)
        rc, _ = self._call(
            "ADL_Adapter_DedicatedVRAMUsage_Get",
            [ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
            ctypes.byref(used),
        )
        if rc != ADL_OK:
            return None
        return used.value * 1024 * 1024

    def vram_total_bytes(self) -> Optional[int]:
        # ADL_Adapter_VRAMUsage_Get isn't reliable for total; use DXGI as fallback.
        # Most ADL builds expose ADL2_Adapter_DedicatedVRAM_Get.
        total = ctypes.c_int(0)
        try:
            rc, _ = self._call(
                "ADL2_Adapter_DedicatedVRAM_Get",
                [ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
                ctypes.byref(total),
            )
            if rc == ADL_OK:
                return total.value * 1024 * 1024
        except AttributeError:
            pass
        return None

    def fan_pct(self) -> Optional[int]:
        v = self._pmlog_sensor(self._pmlog(), ADL_PMLOG_FAN_PERCENTAGE)
        if v is not None:
            return v
        fs = _FanSpeedValue()
        fs.iSize = ctypes.sizeof(_FanSpeedValue)
        fs.iSpeedType = ADL_DL_FANCTRL_SPEED_TYPE_PERCENT
        try:
            rc, _ = self._call(
                "ADL_Overdrive5_FanSpeed_Get",
                [ctypes.c_int, ctypes.c_int, ctypes.POINTER(_FanSpeedValue)],
                0, ctypes.byref(fs),
            )
            return fs.iFanSpeed if rc == ADL_OK else None
        except (AttributeError, OSError):
            return None

    def shutdown(self) -> None:
        try:
            if self._ctx is not None:
                d2 = self._adl.ADL2_Main_Control_Destroy
                d2.argtypes = [ctypes.c_void_p]
                d2.restype = ctypes.c_int
                d2(self._ctx)
        except Exception:
            pass
        try:
            destroy = self._adl.ADL_Main_Control_Destroy
            destroy.restype = ctypes.c_int
            destroy()
        except Exception:
            pass


# --------------------------- detection --------------------------------

def list_gpus() -> list[dict]:
    """Enumerate every GPU we can talk to. Returns dicts with id/name/vendor.

    'id' is a stable token suitable for storing in config: 'nvidia:0', 'amd:3',
    or 'auto' (rendered separately by the GUI).
    """
    gpus: list[dict] = []

    # NVIDIA
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                n = pynvml.nvmlDeviceGetName(h)
                gpus.append({
                    "id": f"nvidia:{i}",
                    "name": n.decode() if isinstance(n, bytes) else n,
                    "vendor": "nvidia",
                })
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        pass

    # AMD
    try:
        adl = ctypes.WinDLL("atiadlxx.dll")
        create = adl.ADL_Main_Control_Create
        create.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int), ctypes.c_int]
        create.restype = ctypes.c_int
        if create(_adl_alloc, 1) == ADL_OK:
            num = ctypes.c_int(0)
            get_n = adl.ADL_Adapter_NumberOfAdapters_Get
            get_n.argtypes = [ctypes.POINTER(ctypes.c_int)]
            get_n.restype = ctypes.c_int
            if get_n(ctypes.byref(num)) == ADL_OK and num.value > 0:
                infos = (_AdapterInfo * num.value)()
                get_info = adl.ADL_Adapter_AdapterInfo_Get
                get_info.argtypes = [ctypes.POINTER(_AdapterInfo), ctypes.c_int]
                get_info.restype = ctypes.c_int
                if get_info(infos, ctypes.sizeof(infos)) == ADL_OK:
                    seen: set[int] = set()
                    for info in infos:
                        if (info.iPresent and info.iVendorID == 0x1002
                                and info.iAdapterIndex not in seen):
                            seen.add(info.iAdapterIndex)
                            gpus.append({
                                "id": f"amd:{info.iAdapterIndex}",
                                "name": info.strAdapterName.decode("utf-8", errors="replace"),
                                "vendor": "amd",
                            })
            adl.ADL_Main_Control_Destroy.restype = ctypes.c_int
            adl.ADL_Main_Control_Destroy()
    except Exception:
        pass

    return gpus


def detect() -> GpuBackend:
    """Auto-pick: NVIDIA if available, otherwise the highest-bus AMD adapter."""
    errors = []
    for cls in (NvidiaBackend, AmdBackend):
        try:
            return cls()
        except Exception as e:
            errors.append(f"{cls.__name__}: {e}")
    raise RuntimeError("No supported GPU backend: " + " | ".join(errors))


def get_backend(gpu_id: str = "auto") -> GpuBackend:
    """Construct a backend for an explicit gpu id ('nvidia:N' / 'amd:N'), or auto."""
    if not gpu_id or gpu_id == "auto":
        return detect()
    try:
        vendor, idx_str = gpu_id.split(":", 1)
        idx = int(idx_str)
    except (ValueError, AttributeError):
        return detect()
    if vendor == "nvidia":
        return NvidiaBackend(idx)
    if vendor == "amd":
        return AmdBackend(idx)
    return detect()

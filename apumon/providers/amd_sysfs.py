"""
APU-Power-Monitor - AMD sysfs provider (primary on Linux)
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

The amdgpu kernel driver publishes everything this dashboard needs under
/sys/class/drm/cardN/device, with no helper binary and no root. Reading files
is also an order of magnitude cheaper than spawning a process per sample,
which matters at a 500 ms cadence.

Units in sysfs: power in microwatts, temperature in millidegrees Celsius,
memory in bytes. All are normalized to W / degC / MiB here.
"""

import glob
import os
import re

from ..metrics import ApuSample
from .base import SensorProvider

_CARD_GLOB = "/sys/class/drm/card[0-9]*/device"


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _read_number(path, scale=1.0):
    text = _read_text(path)
    if text is None:
        return None
    try:
        return float(text) * scale
    except ValueError:
        return None


def _first_number(device, names, scale=1.0):
    """First readable value among several candidate file names."""
    for name in names:
        for path in sorted(glob.glob(os.path.join(device, name))):
            value = _read_number(path, scale)
            if value is not None:
                return value
    return None


def _cpu_model_name():
    """APU marketing name, e.g. 'AMD Ryzen 7 7840U w/ Radeon 780M Graphics'."""
    text = _read_text("/proc/cpuinfo") or ""
    match = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _is_integrated(device):
    """
    APUs share system memory, so their VRAM carve-out is small and there is no
    dedicated memory BAR of consequence. Treat a card as integrated when the
    driver reports an APU-style memory setup; fall back to including it anyway
    rather than silently showing nothing.
    """
    vram_total = _first_number(device, ["mem_info_vram_total"])
    if vram_total is None:
        return True
    return vram_total < 4 * 1024 ** 3


class AmdSysfsProvider(SensorProvider):
    name = "amd-sysfs"
    description = "amdgpu sysfs / hwmon (no root required)"
    platforms = ("Linux",)
    priority = 90

    def __init__(self):
        self._devices = []
        self._model_name = None

    def _discover(self):
        devices = []
        for device in sorted(glob.glob(_CARD_GLOB)):
            uevent = _read_text(os.path.join(device, "uevent")) or ""
            if "amdgpu" not in uevent.lower():
                continue
            if not glob.glob(os.path.join(device, "hwmon/hwmon*")) and not os.path.exists(
                os.path.join(device, "gpu_busy_percent")
            ):
                continue
            devices.append(device)
        # Prefer integrated parts; keep discrete ones only if nothing else.
        integrated = [d for d in devices if _is_integrated(d)]
        return integrated or devices

    def is_available(self):
        if not self.platform_matches():
            return False
        self._devices = self._discover()
        return bool(self._devices)

    def read(self):
        if not self._devices:
            self._devices = self._discover()
        if not self._devices:
            return None
        if self._model_name is None:
            self._model_name = _cpu_model_name() or "AMD APU"

        samples = []
        for index, device in enumerate(self._devices):
            power = _first_number(
                device, ["hwmon/hwmon*/power1_average", "hwmon/hwmon*/power1_input"], 1e-6
            )
            power_cap = _first_number(device, ["hwmon/hwmon*/power1_cap"], 1e-6)
            power_cap_max = _first_number(device, ["hwmon/hwmon*/power1_cap_max"], 1e-6)
            temperature = _first_number(device, ["hwmon/hwmon*/temp1_input"], 1e-3)
            busy = _first_number(device, ["gpu_busy_percent"])

            # On an APU the GTT (shared system memory) figure is the meaningful
            # one; the VRAM carve-out is a small fixed window.
            used = _first_number(device, ["mem_info_gtt_used"], 1 / 1024 ** 2)
            total = _first_number(device, ["mem_info_gtt_total"], 1 / 1024 ** 2)
            notes = ["memory is the shared GTT pool"]
            if used is None:
                used = _first_number(device, ["mem_info_vram_used"], 1 / 1024 ** 2)
                total = _first_number(device, ["mem_info_vram_total"], 1 / 1024 ** 2)
                notes = ["memory is the VRAM carve-out"]

            name = self._model_name
            if len(self._devices) > 1:
                name = f"{name} (card{index})"

            samples.append(
                ApuSample(
                    source=self.name,
                    device_name=name,
                    power_draw=power,
                    power_limit=power_cap,
                    power_max_limit=power_cap_max,
                    gpu_utilization=busy,
                    cpu_utilization=None,
                    temperature=temperature,
                    memory_used=used,
                    memory_total=total,
                    notes=notes,
                )
            )
        return samples or None

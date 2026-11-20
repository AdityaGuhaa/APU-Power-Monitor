"""
APU-Power-Monitor - psutil provider (last resort, any platform)
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Reports what can be read anywhere without drivers or vendor tools: CPU load,
system memory, and a die temperature where the OS exposes one. Power and GPU
utilization are deliberately left as None so the dashboard shows them as
unavailable rather than inventing a number.
"""

import platform

from ..metrics import ApuSample
from .base import SensorProvider

try:
    import psutil
except ImportError:
    psutil = None

_TEMPERATURE_KEYS = ("k10temp", "zenpower", "coretemp", "acpitz", "cpu_thermal")


class PsutilProvider(SensorProvider):
    name = "psutil"
    description = "CPU and system memory only (no power or GPU sensors)"
    priority = -10

    def is_available(self):
        return psutil is not None

    def _temperature(self):
        reader = getattr(psutil, "sensors_temperatures", None)
        if reader is None:
            return None
        try:
            groups = reader()
        except (OSError, AttributeError, NotImplementedError):
            return None
        for key in _TEMPERATURE_KEYS:
            for entry in groups.get(key, []):
                if entry.current:
                    return float(entry.current)
        for entries in groups.values():
            for entry in entries:
                if entry.current:
                    return float(entry.current)
        return None

    def read(self):
        if psutil is None:
            return None
        memory = psutil.virtual_memory()
        return [
            ApuSample(
                source=self.name,
                device_name=platform.processor() or platform.machine() or "Unknown APU",
                power_draw=None,
                power_limit=None,
                power_max_limit=None,
                gpu_utilization=None,
                cpu_utilization=psutil.cpu_percent(interval=None),
                temperature=self._temperature(),
                memory_used=memory.used / 1024 ** 2,
                memory_total=memory.total / 1024 ** 2,
                notes=[
                    "no power or GPU sensors available from this provider",
                    "memory shown is system RAM, not a GPU allocation",
                ],
            )
        ]

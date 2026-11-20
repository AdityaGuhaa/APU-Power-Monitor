"""
APU-Power-Monitor - LibreHardwareMonitor provider (primary on Windows)
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Windows exposes no userspace equivalent of nvidia-smi for integrated
graphics: SoC power and die temperature live behind the SMU and need a kernel
driver to reach. LibreHardwareMonitor already ships that driver, so instead of
duplicating it this provider reads LHM's own HTTP endpoint
(Options -> Remote Web Server -> Run, default port 8085).

The endpoint returns a nested tree of {Text, Value, Children}. Sensor naming
varies by LHM version and by silicon vendor, so the tree is flattened into
(hardware, group, sensor) keys and matched against ordered candidate lists.
"""

import json
import urllib.error
import urllib.request

from ..metrics import ApuSample, clean_float
from .base import SensorProvider

#: Substrings that identify the integrated GPU in a hardware node name.
_GPU_HINTS = (
    "radeon", "vega", "graphics", "iris", "uhd graphics", "hd graphics", "arc",
)
#: Substrings that identify the CPU/SoC in a hardware node name.
_CPU_HINTS = ("ryzen", "core i", "core ultra", "athlon", "apu", "cpu")


def _flatten(node, ancestry, out):
    """Collect every leaf sensor as (ancestry_texts, sensor_text, raw_value)."""
    text = (node.get("Text") or "").strip()
    children = node.get("Children") or []
    value = node.get("Value")
    if not children and value not in (None, ""):
        out.append((ancestry, text, value))
        return
    next_ancestry = ancestry + [text] if text else ancestry
    for child in children:
        _flatten(child, next_ancestry, out)


def _index(leaves):
    """Map (hardware, group, sensor) -> raw value, all lowercased."""
    table = {}
    for ancestry, sensor, value in leaves:
        # ancestry is typically [root, machine, hardware, group, (sub-group)]
        hardware = ancestry[2] if len(ancestry) >= 3 else (ancestry[-1] if ancestry else "")
        group = ancestry[-1] if len(ancestry) >= 4 else ""
        table[(hardware.lower(), group.lower(), sensor.lower())] = value
    return table


def _pick(table, hardware_names, group, sensor_names):
    """First matching sensor value across the given hardware/sensor candidates."""
    for hardware in hardware_names:
        for sensor in sensor_names:
            if (hardware, group, sensor) in table:
                return table[(hardware, group, sensor)]
    return None


def _hardware_matching(table, hints):
    """Distinct hardware names (lowercased) whose name contains any hint."""
    names = []
    for hardware, _group, _sensor in table:
        if hardware in names:
            continue
        if any(hint in hardware for hint in hints):
            names.append(hardware)
    return names


class LibreHardwareMonitorProvider(SensorProvider):
    name = "lhm"
    description = "LibreHardwareMonitor remote web server"
    platforms = ("Windows",)
    priority = 100

    def __init__(self, url, timeout=1.5):
        self.url = url
        self.timeout = timeout
        self._display_names = {}

    # -- transport ----------------------------------------------------------
    def _fetch(self):
        request = urllib.request.Request(self.url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def is_available(self):
        if not self.platform_matches():
            return False
        try:
            tree = self._fetch()
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return False
        leaves = []
        _flatten(tree, [], leaves)
        return bool(leaves)

    # -- reading ------------------------------------------------------------
    def read(self):
        try:
            tree = self._fetch()
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] LibreHardwareMonitor read failed: {exc}")
            return None

        leaves = []
        _flatten(tree, [], leaves)
        if not leaves:
            return None

        # Remember original casing so the UI can show "AMD Radeon 780M", not
        # the lowercased key we match on.
        for ancestry, _sensor, _value in leaves:
            if len(ancestry) >= 3:
                self._display_names[ancestry[2].lower()] = ancestry[2]

        table = _index(leaves)
        gpus = _hardware_matching(table, _GPU_HINTS)
        cpus = _hardware_matching(table, _CPU_HINTS)
        any_hardware = gpus + cpus

        notes = []
        power = _pick(table, cpus, "powers", ("package", "cpu package", "package power"))
        if power is None:
            power = _pick(table, gpus, "powers", ("gpu package", "gpu soc", "gpu ppt", "gpu power"))
            if power is not None:
                notes.append("power is the iGPU rail only, not the whole SoC")
        elif cpus:
            notes.append("power is the whole SoC package (CPU + iGPU)")

        temperature = _pick(table, gpus, "temperatures", ("gpu core", "gpu hot spot", "core"))
        if temperature is None:
            temperature = _pick(
                table, cpus, "temperatures",
                ("core (tctl/tdie)", "cpu package", "core max", "package"),
            )

        gpu_load = _pick(table, gpus, "load", ("gpu core", "d3d 3d", "gpu total"))
        cpu_load = _pick(table, cpus, "load", ("cpu total", "total"))

        memory_used = _pick(
            table, gpus, "data",
            ("gpu memory used", "d3d shared memory used", "gpu memory allocated"),
        )
        memory_total = _pick(table, gpus, "data", ("gpu memory total", "memory total"))

        device_name = None
        for hardware in (gpus + cpus):
            device_name = self._display_names.get(hardware, hardware)
            break

        if not any_hardware:
            notes.append("no APU-like hardware node found in the LHM tree")

        return [
            ApuSample(
                source=self.name,
                device_name=device_name or "Unknown APU",
                power_draw=clean_float(power, minimum=0.0),
                power_limit=None,  # LHM does not expose PPT; see APU_POWER_LIMIT_W
                power_max_limit=None,
                gpu_utilization=clean_float(gpu_load, minimum=0.0, maximum=100.0),
                cpu_utilization=clean_float(cpu_load, minimum=0.0, maximum=100.0),
                temperature=clean_float(temperature),
                memory_used=clean_float(memory_used, minimum=0.0),
                memory_total=clean_float(memory_total, minimum=0.0),
                notes=notes,
            )
        ]

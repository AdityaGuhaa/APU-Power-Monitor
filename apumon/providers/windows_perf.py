"""
APU-Power-Monitor - Windows performance-counter provider (Windows fallback)
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Used when LibreHardwareMonitor is not running. Windows publishes per-engine
GPU utilization and shared GPU memory as PDH counters, which cover utilization
and memory but *not* power or die temperature - those need a kernel driver.

Spawning `typeperf` once per sample would cost more CPU than the metric is
worth, so one long-lived child process streams CSV at 1 Hz and a reader thread
keeps the latest aggregate. PDH resolves wildcard instances only at launch, so
the child is recycled periodically to pick up newly started processes.
"""

import csv
import os
import subprocess
import threading
import time

from ..metrics import ApuSample
from .base import SensorProvider

try:
    import psutil
except ImportError:
    psutil = None

try:
    import winreg
except ImportError:
    winreg = None

_COUNTERS = [
    r"\GPU Engine(*)\Utilization Percentage",
    r"\GPU Process Memory(*)\Shared Usage",
]
#: Seconds before the child is restarted so wildcards re-enumerate.
#: Kept long because each restart costs a few seconds of enumeration.
_RECYCLE_SECONDS = 120.0
#: How long a reading stays valid before it is reported as missing. Must
#: comfortably exceed both the 1 Hz counter cadence and a recycle gap.
_STALE_AFTER = 8.0
#: How long to wait for typeperf to resolve the counter names at startup.
_HEADER_TIMEOUT = 8.0


def _processor_name():
    """
    Marketing name of the SoC, e.g. "12th Gen Intel(R) Core(TM) i5-12450H".
    PROCESSOR_IDENTIFIER only gives the family/model triple, which is useless
    on a dashboard, so the registry is read first.
    """
    if winreg is not None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                name, _type = winreg.QueryValueEx(key, "ProcessorNameString")
                if name:
                    return " ".join(str(name).split())
        except OSError:
            pass
    return os.environ.get("PROCESSOR_IDENTIFIER", "Integrated GPU")


class WindowsPerfProvider(SensorProvider):
    name = "windows-perf"
    description = "Windows GPU performance counters via typeperf"
    platforms = ("Windows",)
    priority = 60

    def __init__(self):
        self._device_name = None
        self._process = None
        self._thread = None
        self._columns = []
        self._lock = threading.Lock()
        self._gpu_utilization = None
        self._shared_mib = None
        self._updated_at = 0.0
        self._started_at = 0.0
        self._stop = threading.Event()

    # -- child process ------------------------------------------------------
    def _spawn(self):
        self._terminate()
        command = ["typeperf", *_COUNTERS, "-si", "1"]
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            print(f"[ERROR] typeperf could not be started: {exc}")
            self._process = None
            return False
        self._columns = []
        self._started_at = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, daemon=True, name="typeperf-reader")
        self._thread.start()
        return True

    def _terminate(self):
        self._stop.set()
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        # Terminating the child closes the pipe from the writer side; closing
        # our end too keeps the file descriptor from leaking on recycle.
        try:
            if process.stdout is not None:
                process.stdout.close()
        except (OSError, ValueError):
            pass

    def _pump(self):
        """Read typeperf's CSV stream until the process ends or we stop it."""
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if self._stop.is_set():
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    row = next(csv.reader([line]))
                except (csv.Error, StopIteration):
                    continue
                if not self._columns:
                    # First non-empty line is the header; column 0 is the timestamp.
                    if len(row) > 1 and "\\" in row[1]:
                        self._columns = [cell.lower() for cell in row]
                    continue
                self._consume(row)
        except (OSError, ValueError):
            # The pipe was closed underneath us by _terminate(); that is the
            # normal way this thread ends.
            return

    def _consume(self, row):
        utilization = 0.0
        shared_bytes = 0.0
        saw_utilization = False
        saw_memory = False
        for index, cell in enumerate(row[1:], start=1):
            if index >= len(self._columns):
                break
            column = self._columns[index]
            try:
                value = float(cell)
            except (TypeError, ValueError):
                continue
            if "utilization percentage" in column:
                # Sum only the 3D engines: other engine types (copy, video
                # decode) would double-count overall busy time.
                if "engtype_3d" in column:
                    utilization += value
                    saw_utilization = True
            elif "shared usage" in column:
                shared_bytes += value
                saw_memory = True

        now = time.monotonic()
        with self._lock:
            if saw_utilization:
                self._gpu_utilization = min(100.0, max(0.0, utilization))
            if saw_memory:
                self._shared_mib = shared_bytes / 1024 ** 2
            if saw_utilization or saw_memory:
                self._updated_at = now

    # -- provider API -------------------------------------------------------
    def is_available(self):
        if not self.platform_matches():
            return False
        if not self._spawn():
            return False
        # Counter names are localized on non-English Windows. A header with
        # resolved instances proves the counters exist here; waiting for the
        # first *data* row would cost another second or two for nothing, since
        # read() already reports a not-yet-populated reading as missing.
        deadline = time.monotonic() + _HEADER_TIMEOUT
        while time.monotonic() < deadline:
            with self._lock:
                if self._columns:
                    return True
            if self._process is None or self._process.poll() is not None:
                break
            time.sleep(0.2)
        self._terminate()
        return False

    def read(self):
        if self._process is None or self._process.poll() is not None:
            if not self._spawn():
                return None
        elif time.monotonic() - self._started_at > _RECYCLE_SECONDS:
            self._spawn()

        now = time.monotonic()
        with self._lock:
            fresh = self._updated_at and (now - self._updated_at) < _STALE_AFTER
            utilization = self._gpu_utilization if fresh else None
            shared_mib = self._shared_mib if fresh else None

        if self._device_name is None:
            self._device_name = _processor_name()

        cpu_utilization = None
        memory_total = None
        if psutil is not None:
            cpu_utilization = psutil.cpu_percent(interval=None)
            # Windows offers roughly half of system RAM as shared GPU memory.
            memory_total = psutil.virtual_memory().total / 1024 ** 2 / 2

        return [
            ApuSample(
                source=self.name,
                device_name=self._device_name,
                power_draw=None,
                power_limit=None,
                power_max_limit=None,
                gpu_utilization=utilization,
                cpu_utilization=cpu_utilization,
                temperature=None,
                memory_used=shared_mib,
                memory_total=memory_total,
                notes=[
                    "power and temperature need LibreHardwareMonitor on Windows",
                    "GPU counters update once per second",
                    "memory budget is estimated as half of system RAM",
                ],
            )
        ]

    def close(self):
        self._terminate()

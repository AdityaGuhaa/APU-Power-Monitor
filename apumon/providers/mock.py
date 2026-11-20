"""
APU-Power-Monitor - Synthetic provider
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Lets the dashboard be developed on any machine, with or without an APU. The
signal is a slow sine with noise plus occasional load spikes, so the charts
look like real telemetry instead of white noise.
"""

import math
import random
import time

from ..metrics import ApuSample
from .base import SensorProvider


class MockProvider(SensorProvider):
    name = "mock"
    description = "synthetic data (no hardware access)"
    priority = -100

    def __init__(self):
        self._started = time.monotonic()
        self._spike_until = 0.0
        self._memory_used = 2800.0

    def is_available(self):
        return True

    def read(self):
        now = time.monotonic()
        elapsed = now - self._started

        # Occasional burst of load, ~1 in 60 samples, lasting a few seconds.
        if now > self._spike_until and random.random() < 0.015:
            self._spike_until = now + random.uniform(2.0, 6.0)
        spiking = now < self._spike_until

        wave = math.sin(elapsed / 7.0) * 0.5 + 0.5
        gpu_load = (55 + wave * 35 + random.uniform(-6, 6)) if spiking else (6 + wave * 14 + random.uniform(-4, 4))
        gpu_load = min(100.0, max(0.0, gpu_load))
        cpu_load = min(100.0, max(0.0, gpu_load * 0.6 + random.uniform(0, 18)))

        power = 7.5 + (gpu_load / 100.0) * 22.0 + (cpu_load / 100.0) * 12.0 + random.uniform(-1.2, 1.2)
        temperature = 42 + (gpu_load / 100.0) * 28 + random.uniform(-1.5, 1.5)

        drift = (gpu_load - 30) * 1.5 + random.uniform(-40, 40)
        self._memory_used = min(7800.0, max(900.0, self._memory_used + drift))

        return [
            ApuSample(
                source=self.name,
                device_name="AMD Radeon 780M Graphics (Mock)",
                power_draw=round(power, 2),
                power_limit=45.0,
                power_max_limit=54.0,
                gpu_utilization=round(gpu_load, 1),
                cpu_utilization=round(cpu_load, 1),
                temperature=round(temperature, 1),
                memory_used=round(self._memory_used, 1),
                memory_total=8192.0,
                notes=["synthetic data"],
            )
        ]

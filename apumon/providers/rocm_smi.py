"""
APU-Power-Monitor - rocm-smi provider (Linux fallback)
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Only used when sysfs is unreadable but a ROCm install is present. Key names in
rocm-smi's JSON output have changed several times across releases, so values
are located by substring match rather than exact key.
"""

import json
import shutil
import subprocess

from ..metrics import ApuSample, clean_float
from .base import SensorProvider

_COMMAND = [
    "rocm-smi",
    "--showpower",
    "--showtemp",
    "--showuse",
    "--showmeminfo", "vram",
    "--showproductname",
    "--json",
]


def _find(card, *fragments):
    """Value of the first key containing every fragment (case-insensitive)."""
    for key, value in card.items():
        lowered = key.lower()
        if all(fragment in lowered for fragment in fragments):
            return value
    return None


class RocmSmiProvider(SensorProvider):
    name = "rocm-smi"
    description = "rocm-smi JSON output"
    platforms = ("Linux",)
    priority = 50

    def is_available(self):
        if not self.platform_matches():
            return False
        if shutil.which("rocm-smi") is None:
            return False
        return self.read() is not None

    def read(self):
        try:
            result = subprocess.run(
                _COMMAND, capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[ERROR] rocm-smi failed: {exc}")
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        samples = []
        for card_id, card in payload.items():
            if not isinstance(card, dict):
                continue
            used = clean_float(_find(card, "vram", "used"), minimum=0.0)
            total = clean_float(_find(card, "vram", "total"), minimum=0.0)
            # rocm-smi reports VRAM in bytes.
            if used is not None and used > 1e6:
                used /= 1024 ** 2
            if total is not None and total > 1e6:
                total /= 1024 ** 2
            samples.append(
                ApuSample(
                    source=self.name,
                    device_name=str(_find(card, "card series") or _find(card, "product") or card_id),
                    power_draw=clean_float(_find(card, "power"), minimum=0.0),
                    power_limit=clean_float(_find(card, "power", "cap"), minimum=0.0),
                    power_max_limit=None,
                    gpu_utilization=clean_float(_find(card, "gpu use"), minimum=0.0, maximum=100.0),
                    cpu_utilization=None,
                    temperature=clean_float(_find(card, "temperature", "edge")
                                            or _find(card, "temperature")),
                    memory_used=used,
                    memory_total=total,
                )
            )
        return samples or None

"""
APU-Power-Monitor - Provider registry
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Detection order is by descending `priority`, filtered to the current platform.
The first provider whose `is_available()` returns True wins; MockProvider sits
at the bottom so the dashboard always has something to draw.
"""

import config

from .amd_sysfs import AmdSysfsProvider
from .base import SensorProvider
from .lhm import LibreHardwareMonitorProvider
from .mock import MockProvider
from .psutil_basic import PsutilProvider
from .rocm_smi import RocmSmiProvider
from .windows_perf import WindowsPerfProvider

__all__ = [
    "SensorProvider",
    "AmdSysfsProvider",
    "LibreHardwareMonitorProvider",
    "MockProvider",
    "PsutilProvider",
    "RocmSmiProvider",
    "WindowsPerfProvider",
    "build_providers",
    "select_provider",
]


def build_providers():
    """All known providers, highest priority first."""
    providers = [
        LibreHardwareMonitorProvider(config.LHM_URL, config.LHM_TIMEOUT),
        AmdSysfsProvider(),
        WindowsPerfProvider(),
        RocmSmiProvider(),
        PsutilProvider(),
        MockProvider(),
    ]
    return sorted(providers, key=lambda provider: provider.priority, reverse=True)


def select_provider(name=None, mock=False):
    """
    Resolve the provider to use.

    `name` pins a specific provider by its `name` attribute ("auto" probes);
    `mock` short-circuits to synthetic data. Unused providers are closed so a
    rejected candidate cannot leave a child process behind.
    """
    candidates = build_providers()

    if mock:
        chosen, rest = MockProvider(), candidates
        for provider in rest:
            provider.close()
        return chosen

    requested = (name or "auto").strip().lower()
    if requested not in ("", "auto"):
        for provider in candidates:
            if provider.name != requested:
                continue
            if not provider.is_available():
                print(
                    f"[WARN] Provider {requested!r} was requested but reports itself "
                    "unavailable; using it anyway."
                )
            for other in candidates:
                if other is not provider:
                    other.close()
            return provider
        valid = ", ".join(provider.name for provider in candidates)
        raise SystemExit(f"Unknown provider {requested!r}. Choose one of: {valid}")

    for index, provider in enumerate(candidates):
        if not provider.platform_matches():
            provider.close()
            continue
        try:
            available = provider.is_available()
        except Exception as exc:  # a probe must never take the app down
            print(f"[WARN] Provider {provider.name!r} failed during detection: {exc}")
            available = False
        if available:
            for other in candidates[index + 1:]:
                other.close()
            return provider
        provider.close()

    return MockProvider()

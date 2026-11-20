"""
APU-Power-Monitor - Normalized metric schema
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Every sensor provider returns ApuSample objects, so the websocket payload has
one stable shape no matter which backend produced it. Fields are Optional on
purpose: `None` means "this machine/provider cannot report it", which is a
different statement from 0.0 and is rendered differently in the UI.
"""

from dataclasses import dataclass, field
from typing import Optional

#: Numeric fields, in the order the UI lists them.
METRIC_FIELDS = (
    "power_draw",
    "power_limit",
    "power_max_limit",
    "gpu_utilization",
    "cpu_utilization",
    "temperature",
    "memory_used",
    "memory_total",
)


def clean_float(value, default=None, minimum=None, maximum=None):
    """
    Coerce a sensor reading to a float, or to `default` when it is missing,
    non-numeric, or one of the many "not supported" spellings hardware tools
    emit. Also strips unit suffixes ("15.3 W", "45 degC", "1,024 MB").
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return default
        lowered = text.lower().strip("[]()")
        if lowered in ("n/a", "na", "not supported", "unsupported", "-", "--", "nan"):
            return default
        # Keep the leading numeric run: "15.3 W" -> "15.3", "1,024 MB" -> "1024"
        digits = []
        for char in text.replace(",", ""):
            if char.isdigit() or char in ".-+":
                digits.append(char)
            elif digits:
                break
        try:
            number = float("".join(digits))
        except ValueError:
            return default
    if number != number:  # NaN
        return default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


@dataclass
class ApuSample:
    """One reading from one device at one instant."""

    source: str
    device_name: str = "Unknown APU"
    power_draw: Optional[float] = None       # watts, SoC / package rail
    power_limit: Optional[float] = None      # watts, sustained (PPT / TDP)
    power_max_limit: Optional[float] = None  # watts, boost ceiling
    gpu_utilization: Optional[float] = None  # percent
    cpu_utilization: Optional[float] = None  # percent
    temperature: Optional[float] = None      # degrees Celsius
    memory_used: Optional[float] = None      # MiB (shared system memory)
    memory_total: Optional[float] = None     # MiB
    notes: list = field(default_factory=list)

    def available(self):
        """Names of the fields this sample actually carries a value for."""
        return [name for name in METRIC_FIELDS if getattr(self, name) is not None]

    def to_payload(self):
        """JSON-ready dict, rounded to a sensible display precision."""
        precision = {
            "power_draw": 2,
            "power_limit": 1,
            "power_max_limit": 1,
            "gpu_utilization": 1,
            "cpu_utilization": 1,
            "temperature": 1,
            "memory_used": 1,
            "memory_total": 1,
        }
        payload = {"source": self.source, "device_name": self.device_name}
        for name in METRIC_FIELDS:
            value = getattr(self, name)
            payload[name] = None if value is None else round(value, precision[name])
        payload["available"] = self.available()
        payload["notes"] = list(self.notes)
        return payload

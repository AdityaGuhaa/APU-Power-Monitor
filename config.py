"""
APU-Power-Monitor - Configuration
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Every setting is read once at import time from the environment, so the whole
app has a single source of truth and no scattered os.environ lookups.
"""

import os
import secrets


def _env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[WARN] {name}={raw!r} is not a number; using {default}.")
        return default


def _env_int(name, default):
    return int(_env_float(name, float(default)))


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- Server -----------------------------------------------------------------
# Defaults to loopback: this dashboard exposes hardware telemetry, so it is not
# published to the LAN unless you ask for it.
HOST = os.environ.get("APU_MONITOR_HOST", "127.0.0.1")
PORT = _env_int("APU_MONITOR_PORT", 5000)

# A generated key is fine here (no persistent sessions). Set the env var if you
# ever put this behind a reverse proxy with multiple workers.
SECRET_KEY = os.environ.get("APU_MONITOR_SECRET_KEY") or secrets.token_hex(16)

# Same-origin only by default; widen deliberately.
CORS_ORIGINS = os.environ.get("APU_MONITOR_CORS_ORIGINS", "")

# --- Sampling ---------------------------------------------------------------
POLL_INTERVAL_MS = _env_int("APU_MONITOR_INTERVAL_MS", 500)
HISTORY_SECONDS = _env_int("APU_MONITOR_HISTORY_SECONDS", 60)

# Stop hitting the hardware when nobody is watching the dashboard.
IDLE_WHEN_NO_CLIENTS = _env_bool("APU_MONITOR_IDLE_WHEN_IDLE", True)

# --- Providers --------------------------------------------------------------
# "auto" (default) probes every provider in registry order and takes the first
# that reports itself available. Set to a provider name to pin one.
PROVIDER = os.environ.get("APU_MONITOR_PROVIDER", "auto").strip().lower()
MOCK_MODE = _env_bool("APU_MONITOR_MOCK", False)

# LibreHardwareMonitor's remote web server (Options -> Remote Web Server -> Run).
LHM_URL = os.environ.get("APU_MONITOR_LHM_URL", "http://127.0.0.1:8085/data.json")
LHM_TIMEOUT = _env_float("APU_MONITOR_LHM_TIMEOUT", 1.5)

# --- Manual power envelope --------------------------------------------------
# Unlike a discrete GPU, an APU rarely reports its sustained (PPT / TDP) or
# boost power ceiling through any portable interface. Set these to draw the
# limit line and lock the power axis; leave them unset and the chart
# auto-scales to the highest value seen so far.
POWER_LIMIT_W = _env_float("APU_POWER_LIMIT_W", 0.0) or None
POWER_MAX_LIMIT_W = _env_float("APU_POWER_MAX_LIMIT_W", 0.0) or None


def history_points():
    """Number of samples held in the rolling window."""
    return max(2, int(HISTORY_SECONDS * 1000 / POLL_INTERVAL_MS))


def summary():
    """Human-readable config dump for the startup banner."""
    return {
        "host": HOST,
        "port": PORT,
        "interval_ms": POLL_INTERVAL_MS,
        "history_seconds": HISTORY_SECONDS,
        "history_points": history_points(),
        "provider": "mock" if MOCK_MODE else PROVIDER,
        "power_limit_w": POWER_LIMIT_W,
        "power_max_limit_w": POWER_MAX_LIMIT_W,
    }

"""
APU-Power-Monitor - Sampling loop
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Owns the background thread that polls the active provider and broadcasts
samples over Socket.IO. Deliberately small and provider-agnostic: it knows
about cadence, idling, failure reporting and the last-known sample, and
nothing about hardware.
"""

import threading
import time

from .metrics import ApuSample


class Monitor:
    """Polls a SensorProvider and emits `apu_data` / `apu_error` events."""

    def __init__(
        self,
        socketio,
        provider,
        interval_ms=500,
        idle_when_no_clients=True,
        power_limit=None,
        power_max_limit=None,
    ):
        self.socketio = socketio
        self.provider = provider
        self.interval = max(0.05, interval_ms / 1000.0)
        self.idle_when_no_clients = idle_when_no_clients
        self.power_limit = power_limit
        self.power_max_limit = power_max_limit

        self._lock = threading.Lock()
        self._clients = 0
        self._running = False
        self._latest = None
        self._failing = False
        self._failures = 0
        self._samples_taken = 0

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        """
        Start the sampling thread. Idempotent, so it is safe to call at import
        time - which is what makes the dashboard work under a production WSGI
        server and not only under `python app.py`.
        """
        with self._lock:
            if self._running:
                return False
            self._running = True
        self.socketio.start_background_task(self._loop)
        return True

    def stop(self):
        with self._lock:
            self._running = False

    # -- client bookkeeping -------------------------------------------------
    def client_connected(self):
        with self._lock:
            self._clients += 1
            return self._clients

    def client_disconnected(self):
        with self._lock:
            self._clients = max(0, self._clients - 1)
            return self._clients

    @property
    def clients(self):
        with self._lock:
            return self._clients

    # -- data ---------------------------------------------------------------
    def meta(self):
        """Static-ish description of the stream, sent to each client on connect."""
        return {
            "provider": self.provider.name,
            "provider_description": self.provider.description,
            "interval_ms": round(self.interval * 1000),
            "power_limit": self.power_limit,
            "power_max_limit": self.power_max_limit,
            "samples_taken": self._samples_taken,
        }

    def latest(self):
        """Last successful payload, so a new client renders immediately."""
        return self._latest

    def _apply_limits(self, sample: ApuSample):
        """
        Fill in the power envelope from configuration when the hardware cannot
        report it. An APU's sustained (PPT) and boost ceilings are usually
        invisible to userspace, so this is how the limit line gets drawn.
        """
        if sample.power_limit is None and self.power_limit is not None:
            sample.power_limit = self.power_limit
            sample.notes.append("power limit from configuration")
        if sample.power_max_limit is None:
            if self.power_max_limit is not None:
                sample.power_max_limit = self.power_max_limit
            elif sample.power_limit is not None:
                sample.power_max_limit = sample.power_limit
        return sample

    def sample_once(self):
        """Read the provider once and return a JSON-ready payload, or None."""
        samples = None
        try:
            samples = self.provider.read()
        except Exception as exc:  # a flaky sensor must not kill the thread
            print(f"[ERROR] Provider {self.provider.name!r} raised: {exc}")
        if not samples:
            return None
        self._samples_taken += 1
        return {
            "timestamp": time.time() * 1000.0,
            "interval_ms": round(self.interval * 1000),
            "provider": self.provider.name,
            "devices": [self._apply_limits(sample).to_payload() for sample in samples],
        }

    # -- loop ---------------------------------------------------------------
    def _report_failure(self):
        self._failures += 1
        if not self._failing:
            self._failing = True
            print(f"[WARN] Provider {self.provider.name!r} stopped returning data.")
        self.socketio.emit(
            "apu_error",
            {
                "message": f"No data from provider '{self.provider.name}'.",
                "consecutive_failures": self._failures,
            },
        )

    def _report_recovery(self):
        if self._failing:
            print(f"[INFO] Provider {self.provider.name!r} recovered.")
        self._failing = False
        self._failures = 0

    def _loop(self):
        print(f"[INFO] Sampling every {self.interval * 1000:.0f} ms via {self.provider.name!r}.")
        while True:
            with self._lock:
                if not self._running:
                    break
                idle = self.idle_when_no_clients and self._clients == 0

            if idle:
                # Nobody is watching: do not touch the hardware at all.
                self.socketio.sleep(self.interval)
                continue

            payload = self.sample_once()
            if payload is None:
                self._report_failure()
            else:
                self._report_recovery()
                self._latest = payload
                self.socketio.emit("apu_data", payload)

            self.socketio.sleep(self.interval)

        print("[INFO] Sampling loop stopped.")
        self.provider.close()

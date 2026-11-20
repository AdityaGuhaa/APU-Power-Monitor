"""
Tests for the sampling loop.
Copyright (c) 2026 Aditya Guha - MIT License.
"""

import unittest

from apumon.metrics import ApuSample
from apumon.monitor import Monitor
from apumon.providers.base import SensorProvider


class FakeSocketIO:
    """Minimal stand-in for flask_socketio.SocketIO."""

    def __init__(self):
        self.emitted = []
        self.tasks = []

    def emit(self, event, payload=None, **_kwargs):
        self.emitted.append((event, payload))

    def start_background_task(self, target, *args, **kwargs):
        self.tasks.append((target, args, kwargs))

    def sleep(self, _seconds):
        pass


class StubProvider(SensorProvider):
    name = "stub"
    description = "stub"

    def __init__(self, sample=None, error=None):
        self.sample = sample
        self.error = error
        self.closed = False
        self.reads = 0

    def is_available(self):
        return True

    def read(self):
        self.reads += 1
        if self.error:
            raise self.error
        return [self.sample] if self.sample else None

    def close(self):
        self.closed = True


def make_sample(**overrides):
    defaults = dict(source="stub", device_name="Test APU", power_draw=10.0)
    defaults.update(overrides)
    return ApuSample(**defaults)


class MonitorTests(unittest.TestCase):
    def test_sample_once_builds_a_payload(self):
        monitor = Monitor(FakeSocketIO(), StubProvider(make_sample()))
        payload = monitor.sample_once()
        self.assertEqual(payload["provider"], "stub")
        self.assertEqual(len(payload["devices"]), 1)
        self.assertEqual(payload["devices"][0]["power_draw"], 10.0)
        self.assertIn("timestamp", payload)
        self.assertEqual(payload["interval_ms"], 500)

    def test_configured_limit_fills_missing_hardware_value(self):
        monitor = Monitor(
            FakeSocketIO(), StubProvider(make_sample()), power_limit=45.0, power_max_limit=54.0
        )
        device = monitor.sample_once()["devices"][0]
        self.assertEqual(device["power_limit"], 45.0)
        self.assertEqual(device["power_max_limit"], 54.0)
        self.assertIn("power limit from configuration", device["notes"])

    def test_hardware_limit_wins_over_configuration(self):
        monitor = Monitor(
            FakeSocketIO(), StubProvider(make_sample(power_limit=28.0)), power_limit=45.0
        )
        device = monitor.sample_once()["devices"][0]
        self.assertEqual(device["power_limit"], 28.0)
        # Max falls back to the sustained limit when nothing else is known.
        self.assertEqual(device["power_max_limit"], 28.0)

    def test_provider_exception_is_contained(self):
        monitor = Monitor(FakeSocketIO(), StubProvider(error=RuntimeError("sensor on fire")))
        self.assertIsNone(monitor.sample_once())

    def test_empty_read_is_reported_as_no_data(self):
        monitor = Monitor(FakeSocketIO(), StubProvider(sample=None))
        self.assertIsNone(monitor.sample_once())

    def test_start_is_idempotent(self):
        socketio = FakeSocketIO()
        monitor = Monitor(socketio, StubProvider(make_sample()))
        self.assertTrue(monitor.start())
        self.assertFalse(monitor.start())
        self.assertEqual(len(socketio.tasks), 1)

    def test_client_counting(self):
        monitor = Monitor(FakeSocketIO(), StubProvider(make_sample()))
        self.assertEqual(monitor.client_connected(), 1)
        self.assertEqual(monitor.client_connected(), 2)
        self.assertEqual(monitor.client_disconnected(), 1)
        self.assertEqual(monitor.client_disconnected(), 0)
        # Never goes negative, even if disconnect arrives twice.
        self.assertEqual(monitor.client_disconnected(), 0)

    def test_loop_skips_hardware_when_no_clients(self):
        socketio = FakeSocketIO()
        provider = StubProvider(make_sample())
        monitor = Monitor(socketio, provider, idle_when_no_clients=True)
        monitor.start()
        target, args, kwargs = socketio.tasks[0]

        # Stop the loop after a fixed number of sleeps so it terminates.
        ticks = {"n": 0}
        original_sleep = socketio.sleep

        def counting_sleep(seconds):
            ticks["n"] += 1
            if ticks["n"] >= 3:
                monitor.stop()
            return original_sleep(seconds)

        socketio.sleep = counting_sleep
        target(*args, **kwargs)

        self.assertEqual(provider.reads, 0)
        self.assertEqual(socketio.emitted, [])
        self.assertTrue(provider.closed)

    def test_loop_emits_while_a_client_is_connected(self):
        socketio = FakeSocketIO()
        provider = StubProvider(make_sample())
        monitor = Monitor(socketio, provider, idle_when_no_clients=True)
        monitor.client_connected()
        monitor.start()
        target, args, kwargs = socketio.tasks[0]

        ticks = {"n": 0}

        def counting_sleep(_seconds):
            ticks["n"] += 1
            if ticks["n"] >= 2:
                monitor.stop()

        socketio.sleep = counting_sleep
        target(*args, **kwargs)

        self.assertEqual(provider.reads, 2)
        self.assertEqual([event for event, _ in socketio.emitted], ["apu_data", "apu_data"])
        self.assertIsNotNone(monitor.latest())

    def test_failure_emits_an_error_event(self):
        socketio = FakeSocketIO()
        monitor = Monitor(socketio, StubProvider(sample=None), idle_when_no_clients=False)
        monitor.start()
        target, args, kwargs = socketio.tasks[0]

        ticks = {"n": 0}

        def counting_sleep(_seconds):
            ticks["n"] += 1
            if ticks["n"] >= 2:
                monitor.stop()

        socketio.sleep = counting_sleep
        target(*args, **kwargs)

        events = [event for event, _ in socketio.emitted]
        self.assertEqual(events, ["apu_error", "apu_error"])
        self.assertEqual(socketio.emitted[-1][1]["consecutive_failures"], 2)

    def test_meta_describes_the_stream(self):
        monitor = Monitor(
            FakeSocketIO(), StubProvider(make_sample()), interval_ms=250, power_limit=30.0
        )
        meta = monitor.meta()
        self.assertEqual(meta["provider"], "stub")
        self.assertEqual(meta["interval_ms"], 250)
        self.assertEqual(meta["power_limit"], 30.0)


if __name__ == "__main__":
    unittest.main()

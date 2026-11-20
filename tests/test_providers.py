"""
Tests for sensor providers and provider selection.
Copyright (c) 2026 Aditya Guha - MIT License.
"""

import unittest

from apumon.metrics import METRIC_FIELDS, ApuSample
from apumon.providers import MockProvider, build_providers, select_provider
from apumon.providers.lhm import _flatten, _index, _pick


class MockProviderTests(unittest.TestCase):
    def test_is_always_available(self):
        self.assertTrue(MockProvider().is_available())

    def test_returns_a_complete_sample(self):
        samples = MockProvider().read()
        self.assertEqual(len(samples), 1)
        sample = samples[0]
        self.assertIsInstance(sample, ApuSample)
        for name in METRIC_FIELDS:
            self.assertIsNotNone(getattr(sample, name), msg=name)

    def test_values_stay_in_plausible_ranges(self):
        provider = MockProvider()
        for _ in range(200):
            sample = provider.read()[0]
            self.assertGreaterEqual(sample.power_draw, 0.0)
            self.assertLessEqual(sample.gpu_utilization, 100.0)
            self.assertGreaterEqual(sample.gpu_utilization, 0.0)
            self.assertLessEqual(sample.memory_used, sample.memory_total)


class RegistryTests(unittest.TestCase):
    def test_providers_are_ordered_by_priority(self):
        priorities = [provider.priority for provider in build_providers()]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_every_provider_has_a_unique_name(self):
        names = [provider.name for provider in build_providers()]
        self.assertEqual(len(names), len(set(names)))

    def test_mock_flag_short_circuits_detection(self):
        self.assertIsInstance(select_provider(mock=True), MockProvider)

    def test_unknown_provider_name_is_rejected(self):
        with self.assertRaises(SystemExit):
            select_provider(name="does-not-exist")

    def test_auto_detection_always_resolves(self):
        provider = select_provider(name="auto")
        self.addCleanup(provider.close)
        self.assertTrue(hasattr(provider, "read"))


class LhmTreeTests(unittest.TestCase):
    TREE = {
        "Text": "Sensor",
        "Children": [
            {
                "Text": "MACHINE",
                "Children": [
                    {
                        "Text": "AMD Ryzen 7 7840U",
                        "Children": [
                            {"Text": "Powers", "Children": [
                                {"Text": "Package", "Value": "15.3 W"},
                            ]},
                            {"Text": "Load", "Children": [
                                {"Text": "CPU Total", "Value": "12.5 %"},
                            ]},
                        ],
                    },
                    {
                        "Text": "AMD Radeon 780M",
                        "Children": [
                            {"Text": "Load", "Children": [
                                {"Text": "GPU Core", "Value": "8.0 %"},
                            ]},
                            {"Text": "Data", "Children": [
                                {"Text": "GPU Memory Used", "Value": "1,024 MB"},
                            ]},
                        ],
                    },
                ],
            }
        ],
    }

    def test_flatten_collects_only_leaves(self):
        leaves = []
        _flatten(self.TREE, [], leaves)
        sensors = sorted(sensor for _ancestry, sensor, _value in leaves)
        self.assertEqual(sensors, ["CPU Total", "GPU Core", "GPU Memory Used", "Package"])

    def test_pick_finds_sensors_by_hardware_and_group(self):
        leaves = []
        _flatten(self.TREE, [], leaves)
        table = _index(leaves)
        self.assertEqual(_pick(table, ["amd ryzen 7 7840u"], "powers", ("package",)), "15.3 W")
        self.assertEqual(_pick(table, ["amd radeon 780m"], "load", ("gpu core",)), "8.0 %")
        self.assertIsNone(_pick(table, ["amd radeon 780m"], "powers", ("package",)))


if __name__ == "__main__":
    unittest.main()

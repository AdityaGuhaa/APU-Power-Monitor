"""
Tests for the normalized metric schema.
Copyright (c) 2026 Aditya Guha - MIT License.
"""

import unittest

from apumon.metrics import ApuSample, clean_float


class CleanFloatTests(unittest.TestCase):
    def test_parses_plain_numbers(self):
        self.assertEqual(clean_float(12), 12.0)
        self.assertEqual(clean_float("12.5"), 12.5)
        self.assertEqual(clean_float(-3.5), -3.5)

    def test_strips_units_and_separators(self):
        self.assertEqual(clean_float("15.3 W"), 15.3)
        self.assertEqual(clean_float("45.0 °C"), 45.0)
        self.assertEqual(clean_float("1,024 MB"), 1024.0)
        self.assertEqual(clean_float("8 %"), 8.0)

    def test_missing_values_become_default(self):
        for raw in (None, "", "   ", "[N/A]", "N/A", "Not Supported", "--", "nan"):
            self.assertIsNone(clean_float(raw), msg=repr(raw))
        self.assertEqual(clean_float("[N/A]", default=0.0), 0.0)

    def test_rejects_non_numeric_text(self):
        self.assertIsNone(clean_float("unknown"))
        self.assertIsNone(clean_float(True))

    def test_clamps_to_range(self):
        self.assertEqual(clean_float("120 %", minimum=0.0, maximum=100.0), 100.0)
        self.assertEqual(clean_float("-5 W", minimum=0.0), 0.0)


class ApuSampleTests(unittest.TestCase):
    def test_available_lists_only_present_fields(self):
        sample = ApuSample(source="test", power_draw=12.0, temperature=50.0)
        self.assertEqual(sample.available(), ["power_draw", "temperature"])

    def test_payload_keeps_none_distinct_from_zero(self):
        sample = ApuSample(source="test", power_draw=0.0, gpu_utilization=None)
        payload = sample.to_payload()
        self.assertEqual(payload["power_draw"], 0.0)
        self.assertIsNone(payload["gpu_utilization"])
        self.assertNotIn("gpu_utilization", payload["available"])

    def test_payload_rounds_for_display(self):
        sample = ApuSample(source="test", power_draw=12.3456789, memory_used=1024.987654)
        payload = sample.to_payload()
        self.assertEqual(payload["power_draw"], 12.35)
        self.assertEqual(payload["memory_used"], 1025.0)

    def test_notes_are_copied_not_shared(self):
        sample = ApuSample(source="test", notes=["a"])
        payload = sample.to_payload()
        payload["notes"].append("b")
        self.assertEqual(sample.notes, ["a"])


if __name__ == "__main__":
    unittest.main()

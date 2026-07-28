import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.calibration import load_device_calibration
from backend.power_calibration import resolve_power_offset_db


class CalibrationTests(unittest.TestCase):
    def test_device_defaults_and_serial_overrides_are_merged(self):
        document = {
            "devices": {
                "PLUTO": {
                    "default": {
                        "frequency_axis_offset_hz": 10.0,
                        "power_offset_db": 30.0,
                    },
                    "serials": {
                        "P123": {
                            "power_offset_db": 35.0,
                        }
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with patch.dict(
                os.environ,
                {"FREQANALYZER_CALIBRATION": str(path)},
            ):
                calibration = load_device_calibration("pluto", "P123")

        self.assertEqual(calibration["frequency_axis_offset_hz"], 10.0)
        self.assertEqual(calibration["power_offset_db"], 35.0)

    def test_power_offset_interpolates_frequency_and_enforces_gain_range(self):
        calibration = {
            "power_cal_vga_min_db": 20.0,
            "power_cal_vga_max_db": 40.0,
            "power_base_offset_table": [
                {"freq_hz": 100e6, "base_offset_db": -10.0},
                {"freq_hz": 200e6, "base_offset_db": -20.0},
            ],
        }

        self.assertAlmostEqual(
            resolve_power_offset_db(calibration, vga_db=30.0, freq_hz=150e6),
            -45.0,
        )
        self.assertIsNone(
            resolve_power_offset_db(calibration, vga_db=10.0, freq_hz=150e6)
        )


if __name__ == "__main__":
    unittest.main()

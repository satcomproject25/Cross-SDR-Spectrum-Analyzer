import csv
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from frontend.recorder import Recorder


class RecorderTests(unittest.TestCase):
    def test_csv_exports_raw_dbfs_and_calibrated_dbm_columns(self):
        raw = np.array([-80.0, -40.0])
        frame = types.SimpleNamespace(
            frequency=np.array([100e6, 101e6]),
            amplitude=raw,
            max_hold=raw + 1.0,
            min_hold=raw - 1.0,
            average=raw + 0.5,
            amplitude_dbfs=raw,
            max_hold_dbfs=raw + 1.0,
            min_hold_dbfs=raw - 1.0,
            average_dbfs=raw + 0.5,
            amplitude_dbm=raw + 35.0,
            max_hold_dbm=raw + 36.0,
            min_hold_dbm=raw + 34.0,
            average_dbm=raw + 35.5,
        )
        recorder = Recorder.__new__(Recorder)
        recorder.main_window = None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spectrum.csv"
            with patch(
                "frontend.recorder.QFileDialog.getSaveFileName",
                return_value=(str(path), "CSV Files (*.csv)"),
            ):
                result = recorder.export_csv(frame)

            self.assertEqual(result, str(path))
            with path.open(newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(
            rows[0],
            [
                "frequency_hz",
                "amplitude_dbfs",
                "max_hold_dbfs",
                "min_hold_dbfs",
                "average_dbfs",
                "amplitude_dbm",
                "max_hold_dbm",
                "min_hold_dbm",
                "average_dbm",
            ],
        )
        self.assertEqual(float(rows[1][1]), -80.0)
        self.assertEqual(float(rows[1][5]), -45.0)


if __name__ == "__main__":
    unittest.main()

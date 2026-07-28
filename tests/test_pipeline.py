import unittest

import numpy as np

from backend.controller import AnalyzerPipeline
from backend.models import AcquisitionConfig


class AnalyzerPipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = AcquisitionConfig(
            device_type="HACKRF",
            center_frequency=100e6,
            sample_rate=2e6,
            span=1e6,
            gain=20,
            fft_size=4096,
        )
        self.pipeline = AnalyzerPipeline(self.config, "Synthetic SDR")

    def tone(self, amplitude, offset_hz=125e3):
        n = np.arange(self.config.fft_size)
        return (amplitude * np.exp(2j * np.pi * offset_hz * n / self.config.sample_rate)).astype(
            np.complex64
        )

    def test_tone_frequency_and_level(self):
        frame = self.pipeline.process(self.tone(0.5))
        index = int(np.argmax(frame.amplitude))
        self.assertAlmostEqual(frame.frequency[index], 100.125e6, delta=frame.rbw)
        self.assertAlmostEqual(frame.amplitude[index], 20 * np.log10(0.5), delta=0.1)
        self.assertEqual(frame.device_name, "Synthetic SDR")
        self.assertGreater(len(frame.peaks), 0)

    def test_holds_and_average_accumulate(self):
        loud = self.pipeline.process(self.tone(0.8))
        quiet = self.pipeline.process(self.tone(0.2))
        index = int(np.argmax(loud.amplitude))
        self.assertAlmostEqual(quiet.max_hold[index], loud.amplitude[index], places=4)
        self.assertAlmostEqual(quiet.min_hold[index], quiet.amplitude[index], places=4)
        expected_average = 10.0 * np.log10(
            (
                10.0 ** (loud.amplitude[index] / 10.0)
                + 10.0 ** (quiet.amplitude[index] / 10.0)
            )
            / 2.0
        )
        self.assertAlmostEqual(
            quiet.average[index], expected_average, places=4
        )

    def test_min_hold_ignores_dsp_numerical_floor(self):
        first = self.pipeline.process(self.tone(0.5))
        floor_frame = self.pipeline.process(
            np.zeros(self.config.fft_size, dtype=np.complex64)
        )
        self.assertTrue(np.all(floor_frame.amplitude == -140.0))
        self.assertTrue(np.all(floor_frame.min_hold > -139.0))
        self.assertTrue(np.all(np.isfinite(floor_frame.min_hold)))

    def test_min_hold_can_be_reset_independently(self):
        self.pipeline.process(self.tone(0.1))
        self.pipeline.traces.reset_min_hold()
        restarted = self.pipeline.process(self.tone(0.5))
        valid = restarted.amplitude > -139.0
        self.assertTrue(np.allclose(restarted.min_hold[valid], restarted.amplitude[valid]))
        self.assertTrue(np.all(restarted.min_hold > -139.0))

    def test_display_span_is_cropped_and_metrics_are_finite(self):
        frame = self.pipeline.process(self.tone(0.5))
        self.assertLessEqual(frame.frequency[-1] - frame.frequency[0], self.config.span)
        self.assertTrue(np.isfinite(frame.noise_floor))
        self.assertTrue(np.isfinite(frame.channel_power))
        self.assertGreaterEqual(frame.bandwidth, 0)

    def test_power_calibration_covers_traces_peaks_and_measurements(self):
        offset = 37.25
        pipeline = AnalyzerPipeline(
            self.config, "Calibrated SDR", power_offset_db=offset
        )
        frame = pipeline.process(self.tone(0.5))

        self.assertEqual(frame.amplitude_unit, "dBm")
        self.assertTrue(frame.power_calibrated)
        self.assertTrue(np.allclose(frame.amplitude_dbm, frame.amplitude_dbfs + offset))
        self.assertTrue(np.allclose(frame.max_hold_dbm, frame.max_hold_dbfs + offset))
        self.assertTrue(np.allclose(frame.min_hold_dbm, frame.min_hold_dbfs + offset))
        self.assertTrue(np.allclose(frame.average_dbm, frame.average_dbfs + offset))
        self.assertAlmostEqual(
            frame.peaks_dbm[0].amplitude,
            frame.peaks[0].amplitude + offset,
        )
        self.assertAlmostEqual(
            frame.noise_floor_dbm, frame.noise_floor_dbfs + offset
        )
        self.assertAlmostEqual(
            frame.channel_power_dbm, frame.channel_power_dbfs + offset
        )

    def test_invalid_power_offsets_do_not_mislabel_dbfs_as_dbm(self):
        for offset in (None, float("nan"), float("inf"), "not-a-number"):
            with self.subTest(offset=offset):
                pipeline = AnalyzerPipeline(
                    self.config, "Uncalibrated SDR", power_offset_db=offset
                )
                frame = pipeline.process(self.tone(0.5))
                self.assertFalse(frame.power_calibrated)
                self.assertEqual(frame.amplitude_unit, "dBFS")
                self.assertIsNone(frame.amplitude_dbm)
                self.assertIsNone(frame.noise_floor_dbm)
                self.assertIsNone(frame.channel_power_dbm)


if __name__ == "__main__":
    unittest.main()

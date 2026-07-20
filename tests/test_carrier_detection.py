import unittest

import numpy as np

from backend.carrier_detection import CarrierDetectionEngine


class CarrierDetectionEngineTests(unittest.TestCase):
    @staticmethod
    def spectrum(span_hz=20e6, bins=4096):
        rng = np.random.default_rng(20260720)
        frequency = np.linspace(70e6 - span_hz / 2, 70e6 + span_hz / 2, bins)
        normalized = (frequency - frequency[0]) / span_hz
        amplitude = -78.0 + 2.0 * (normalized - 0.5)
        amplitude += rng.normal(0.0, 2.2, bins)

        # This broad, low-prominence floor hump reproduced the unwanted band
        # shown near 62 MHz in the supplied HackRF capture.
        false_hump = (normalized >= 0.098) & (normalized <= 0.112)
        amplitude[false_hump] += 5.5

        first = (normalized >= 0.46) & (normalized <= 0.54)
        second = (normalized >= 0.66) & (normalized <= 0.74)
        amplitude[first] = -46.0 + rng.normal(0.0, 2.0, np.count_nonzero(first))
        amplitude[second] = -56.0 + rng.normal(0.0, 2.0, np.count_nonzero(second))
        return frequency, amplitude, (first, second)

    def test_rejects_amplified_noise_floor_and_keeps_real_carriers(self):
        _, amplitude, expected_masks = self.spectrum()
        carriers = CarrierDetectionEngine().detect(amplitude)

        self.assertEqual(len(carriers), 2)
        for carrier, expected_mask in zip(carriers, expected_masks):
            expected_bins = np.flatnonzero(expected_mask)
            self.assertLessEqual(abs(carrier.left_bin - expected_bins[0]), 1)
            self.assertLessEqual(abs(carrier.right_bin - expected_bins[-1]), 1)

    def test_rejects_incomplete_fft_edge_regions(self):
        _, amplitude, _ = self.spectrum()
        amplitude[:180] = np.linspace(-45.0, -74.0, 180)
        carriers = CarrierDetectionEngine().detect(amplitude)
        self.assertEqual(len(carriers), 2)
        self.assertTrue(all(carrier.left_bin > 180 for carrier in carriers))

    def test_detection_is_independent_of_frequency_span_and_device_rate(self):
        detector = CarrierDetectionEngine()
        for span_hz in (2e6, 20e6, 160e6):
            for bins in (1024, 4096, 8192):
                with self.subTest(span=span_hz, bins=bins):
                    _, amplitude, _ = self.spectrum(
                        span_hz=span_hz,
                        bins=bins,
                    )
                    self.assertEqual(len(detector.detect(amplitude)), 2)

    def test_isolated_high_noise_spikes_are_not_carrier_cores(self):
        amplitude = np.full(4096, -80.0)
        amplitude[[500, 1800, 3000]] = -35.0
        self.assertEqual(CarrierDetectionEngine().detect(amplitude), [])


if __name__ == "__main__":
    unittest.main()

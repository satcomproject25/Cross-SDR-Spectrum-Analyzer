"""Measurements derived from each live spectrum."""

import numpy as np

from .models import MeasurementData


class MeasurementEngine:
    @staticmethod
    def _interpolated_peak_hz(amplitude: np.ndarray, frequency: np.ndarray) -> float:
        """Sub-bin peak location by 3-point parabolic fit on the log-magnitude.

        Recovers roughly an order of magnitude of frequency resolution over a bare
        argmax, which otherwise quantizes to +/- half a bin. Falls back to the raw
        bin at the array edges or on a degenerate (flat/noisy) fit.
        """
        k = int(np.argmax(amplitude))
        if k <= 0 or k >= amplitude.size - 1:
            return float(frequency[k])
        y0, y1, y2 = amplitude[k - 1], amplitude[k], amplitude[k + 1]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) < 1e-12:                 # flat top: no usable curvature
            return float(frequency[k])
        delta = 0.5 * (y0 - y2) / denom        # in bins, nominally within +/-0.5
        if not np.isfinite(delta) or abs(delta) > 1.0:
            return float(frequency[k])
        bin_hz = float(frequency[1] - frequency[0])
        return float(frequency[k]) + delta * bin_hz
    
    def update(self, traces) -> MeasurementData:
        amplitude = np.asarray(traces.live, dtype=np.float64)
        frequency = np.asarray(traces.frequency, dtype=np.float64)
        if amplitude.size == 0:
            raise ValueError("Cannot measure an empty spectrum")

        noise_floor = float(np.median(amplitude))
        power = np.power(10.0, amplitude / 10.0)
        total_power = float(np.sum(power))
        channel_power = float(10.0 * np.log10(max(total_power, 1e-24)))

        cumulative = np.cumsum(power)
        lower = min(int(np.searchsorted(cumulative, total_power * 0.005)), len(frequency) - 1)
        upper = min(int(np.searchsorted(cumulative, total_power * 0.995)), len(frequency) - 1)
        occupied_bandwidth = float(max(0.0, frequency[upper] - frequency[lower]))

        return MeasurementData(
            peak_frequency=self._interpolated_peak_hz(amplitude, frequency),
            peak_amplitude=float(np.max(amplitude)),
            noise_floor=noise_floor,
            occupied_bandwidth=occupied_bandwidth,
            channel_power=channel_power,
        )

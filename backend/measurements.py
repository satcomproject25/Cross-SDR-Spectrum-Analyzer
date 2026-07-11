"""Measurements derived from each live spectrum."""

import numpy as np

from .models import MeasurementData


class MeasurementEngine:
    def __init__(self, signal_threshold_db: float = 6.0):
        self.signal_threshold_db = signal_threshold_db

    def update(self, traces) -> MeasurementData:
        amplitude = np.asarray(traces.live, dtype=np.float64)
        frequency = np.asarray(traces.frequency, dtype=np.float64)
        if amplitude.size == 0:
            raise ValueError("Cannot measure an empty spectrum")

        peak_bin = int(np.argmax(amplitude))
        noise_floor = float(np.median(amplitude))
        power = np.power(10.0, amplitude / 10.0)
        total_power = float(np.sum(power))
        channel_power = float(10.0 * np.log10(max(total_power, 1e-24)))

        cumulative = np.cumsum(power)
        lower = min(int(np.searchsorted(cumulative, total_power * 0.005)), len(frequency) - 1)
        upper = min(int(np.searchsorted(cumulative, total_power * 0.995)), len(frequency) - 1)
        occupied_bandwidth = float(max(0.0, frequency[upper] - frequency[lower]))

        above_noise = np.flatnonzero(amplitude >= noise_floor + self.signal_threshold_db)
        carrier_bandwidth = 0.0
        if above_noise.size:
            # Measure the contiguous detected region containing the strongest bin.
            left = peak_bin
            right = peak_bin
            threshold = noise_floor + self.signal_threshold_db
            while left > 0 and amplitude[left - 1] >= threshold:
                left -= 1
            while right + 1 < amplitude.size and amplitude[right + 1] >= threshold:
                right += 1
            carrier_bandwidth = float(max(0.0, frequency[right] - frequency[left]))

        return MeasurementData(
            peak_frequency=float(frequency[peak_bin]),
            peak_amplitude=float(amplitude[peak_bin]),
            noise_floor=noise_floor,
            occupied_bandwidth=occupied_bandwidth,
            channel_power=channel_power,
            carrier_bandwidth=carrier_bandwidth,
        )

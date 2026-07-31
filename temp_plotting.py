#!/usr/bin/env python3
"""
Plot synthetic spectrum with carrier detection thresholds.

Displays:
 - original (unsmoothed) amplitude
 - smoothed trace used in detection
 - noise floor (median)
 - enter threshold line (noise + max(enter_threshold_db, 6*noise_sigma))
 - exit threshold line (noise + max(exit_threshold_db, 3*noise_sigma))
 - detected carrier regions (shaded)

Runs the exact CarrierDetectionEngine from the attached code.
"""

import numpy as np
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------
# Copy of the carrier detection engine (unchanged)
# ----------------------------------------------------------------------
from dataclasses import dataclass


@dataclass(slots=True)
class CarrierRegion:
    left_bin: int
    right_bin: int
    center_bin: int
    peak_bin: int
    peak_power: float
    noise_floor: float
    confidence: float = 1.0


class CarrierDetectionEngine:
    """Detect sustained occupied bands and align them to their onset edges."""

    def __init__(
        self,
        enter_threshold_db: float = 20.0,
        exit_threshold_db: float = 3.0,
        smoothing_window: int | None = None,
        minimum_width_bins: int = 50,
        merge_gap_bins: int = 0,
    ):
        if enter_threshold_db <= exit_threshold_db:
            raise ValueError(
                "enter_threshold_db must be greater than exit_threshold_db"
            )
        if exit_threshold_db <= 0:
            raise ValueError("exit_threshold_db must be positive")
        if smoothing_window is not None and smoothing_window < 1:
            raise ValueError("smoothing_window must be positive")
        if minimum_width_bins < 1:
            raise ValueError("minimum_width_bins must be at least one")
        if merge_gap_bins < 0:
            raise ValueError("merge_gap_bins cannot be negative")

        self.enter_threshold_db = float(enter_threshold_db)
        self.exit_threshold_db = float(exit_threshold_db)
        self.smoothing_window = smoothing_window
        self.minimum_width_bins = int(minimum_width_bins)
        self.merge_gap_bins = int(merge_gap_bins)

    def _window_for(self, size: int) -> int:
        if self.smoothing_window is None:
            window = max(3, min(11, 2 * int(round(size / 1024.0)) + 1))
        else:
            window = int(self.smoothing_window)
        if window % 2 == 0:
            window += 1
        if window > size:
            window = size if size % 2 else size - 1
        return max(1, window)

    @staticmethod
    def _moving_average(spectrum: np.ndarray, window: int) -> np.ndarray:
        if window <= 1:
            return spectrum.copy()
        half = window // 2
        padded = np.pad(spectrum, (half, half), mode="edge")
        cumulative = np.cumsum(np.insert(padded, 0, 0.0))
        return (cumulative[window:] - cumulative[:-window]) / window

    def smooth(self, spectrum: np.ndarray) -> np.ndarray:
        spectrum = np.asarray(spectrum, dtype=np.float64)
        return self._moving_average(spectrum, self._window_for(spectrum.size))

    @staticmethod
    def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
        padded = np.pad(mask.astype(np.int8), (1, 1))
        changes = np.diff(padded)
        starts = np.flatnonzero(changes == 1)
        stops = np.flatnonzero(changes == -1) - 1
        return list(zip(starts.tolist(), stops.tolist()))

    @classmethod
    def _longest_run(cls, mask: np.ndarray) -> int:
        return max(
            (stop - start + 1 for start, stop in cls._runs(mask)),
            default=0,
        )

    @staticmethod
    def _noise_statistics(smoothed: np.ndarray) -> tuple[float, float]:
        upper_noise_limit = float(np.percentile(smoothed, 60.0))
        noise_samples = smoothed[smoothed <= upper_noise_limit]
        noise_floor = float(np.median(noise_samples))

        differences = np.diff(smoothed)
        if differences.size:
            median_difference = float(np.median(differences))
            difference_mad = float(
                np.median(np.abs(differences - median_difference))
            )
            noise_sigma = 1.4826 * difference_mad / np.sqrt(2.0)
        else:
            noise_sigma = 0.0
        return noise_floor, max(0.25, float(noise_sigma))

    def estimate_noise(self, spectrum: np.ndarray) -> float:
        smoothed = self.smooth(np.asarray(spectrum, dtype=np.float64))
        noise_floor, _ = self._noise_statistics(smoothed)
        return noise_floor

    @staticmethod
    def _first_confirmed_above(
        amplitude: np.ndarray,
        threshold: float,
        start: int,
        stop: int,
        confirmation_bins: int = 3,
    ) -> int | None:
        stop = min(stop, amplitude.size - confirmation_bins)
        for index in range(max(0, start), stop + 1):
            if np.all(amplitude[index : index + confirmation_bins] >= threshold):
                return index
        return None

    @staticmethod
    def _last_confirmed_above(
        amplitude: np.ndarray,
        threshold: float,
        start: int,
        stop: int,
        confirmation_bins: int = 3,
    ) -> int | None:
        start = max(start, confirmation_bins - 1)
        for index in range(min(stop, amplitude.size - 1), start - 1, -1):
            if np.all(
                amplitude[index - confirmation_bins + 1 : index + 1] >= threshold
            ):
                return index
        return None

    def _merge_regions(self, regions: list[CarrierRegion]) -> list[CarrierRegion]:
        if not regions or self.merge_gap_bins == 0:
            return regions
        merged = [regions[0]]
        for current in regions[1:]:
            previous = merged[-1]
            gap = current.left_bin - previous.right_bin - 1
            if gap > self.merge_gap_bins:
                merged.append(current)
                continue
            peak = previous if previous.peak_power >= current.peak_power else current
            previous.right_bin = current.right_bin
            previous.center_bin = (previous.left_bin + previous.right_bin) // 2
            previous.peak_bin = peak.peak_bin
            previous.peak_power = peak.peak_power
            previous.confidence = max(previous.confidence, current.confidence)
        return merged

    def detect(self, amplitude: np.ndarray) -> list[CarrierRegion]:
        amplitude = np.asarray(amplitude, dtype=np.float64)
        if amplitude.ndim != 1:
            raise ValueError("Carrier detection expects a one-dimensional spectrum")
        if amplitude.size < 7:
            return []

        finite = np.isfinite(amplitude)
        if np.count_nonzero(finite) < 7:
            return []
        if not np.all(finite):
            amplitude = np.interp(
                np.arange(amplitude.size),
                np.flatnonzero(finite),
                amplitude[finite],
            )

        window = self._window_for(amplitude.size)
        core_trace = self._moving_average(amplitude, window)
        noise, noise_sigma = self._noise_statistics(core_trace)

        enter_level = noise + max(self.enter_threshold_db, 6.0 * noise_sigma)
        exit_level = noise + max(self.exit_threshold_db, 3.0 * noise_sigma)
        core_mask = core_trace >= enter_level
        occupied_mask = core_trace >= exit_level
        carriers: list[CarrierRegion] = []

        for region_start, region_stop in self._runs(occupied_mask):
            if region_start == 0 or region_stop == amplitude.size - 1:
                continue

            region_core = core_mask[region_start : region_stop + 1]
            if self._longest_run(region_core) < self.minimum_width_bins:
                continue

            core_bins = np.flatnonzero(region_core) + region_start
            core_start = int(core_bins[0])
            core_stop = int(core_bins[-1])
            padding = window // 2 + 2

            left_bin = self._first_confirmed_above(
                amplitude,
                exit_level,
                max(1, region_start - padding),
                min(region_stop, core_start + padding),
            )
            right_bin = self._last_confirmed_above(
                amplitude,
                exit_level,
                max(region_start, core_stop - padding),
                min(amplitude.size - 2, region_stop + padding),
            )
            if left_bin is None or right_bin is None or right_bin <= left_bin:
                continue

            segment = amplitude[left_bin : right_bin + 1]
            peak_bin = left_bin + int(np.argmax(segment))
            peak_power = float(amplitude[peak_bin])
            confidence = float(
                np.clip(
                    (peak_power - enter_level)
                    / max(self.enter_threshold_db, 1.0),
                    0.0,
                    1.0,
                )
            )
            carriers.append(
                CarrierRegion(
                    left_bin=left_bin,
                    right_bin=right_bin,
                    center_bin=(left_bin + right_bin) // 2,
                    peak_bin=peak_bin,
                    peak_power=peak_power,
                    noise_floor=noise,
                    confidence=confidence,
                )
            )

        return self._merge_regions(carriers)


# ----------------------------------------------------------------------
# Create a synthetic spectrum for demonstration
# ----------------------------------------------------------------------
def generate_test_spectrum(num_bins=1024, noise_floor_dbm=-85.0):
    """Return 1D amplitude array (dB scale) with noise + a few 'carriers'."""
    rng = np.random.default_rng(42)
    # Gaussian noise in linear scale, then convert to dB
    noise_linear = 10 ** (noise_floor_dbm / 10.0)
    raw = rng.normal(loc=0.0, scale=np.sqrt(noise_linear / 2), size=num_bins) + \
          1j * rng.normal(loc=0.0, scale=np.sqrt(noise_linear / 2), size=num_bins)

    # Add a few raised bumps (carriers)
    carrier_params = [
        (200, 60, 15),   # center_bin, width_bins, snr_db
        (450, 40, 20),
        (700, 80, 12),
        (850, 30, 25),
    ]
    for center, width, snr in carrier_params:
        # Gaussian bump in linear scale
        x = np.arange(num_bins)
        bump = np.exp(-0.5 * ((x - center) / (width / 2.355)) ** 2)  # FWHM approx width
        bump_linear = 10 ** ((noise_floor_dbm + snr) / 10.0) * bump
        raw += bump_linear

    # Power spectrum (linear) -> dB
    power = np.abs(raw) ** 2
    # Ensure no zero values
    power[power < 1e-18] = 1e-18
    db = 10 * np.log10(power)
    return db


# ----------------------------------------------------------------------
# Main: run detection and plot
# ----------------------------------------------------------------------
def main():
    # Generate spectrum
    num_bins = 1024
    amplitude = generate_test_spectrum(num_bins)

    # Create engine with default parameters
    engine = CarrierDetectionEngine(
        enter_threshold_db=10.0,
        exit_threshold_db=3.0,
        minimum_width_bins=20,   # lower to catch our test bumps
        merge_gap_bins=0,
    )

    # Replicate the first part of engine.detect() to get intermediate values
    # (we need the smoothed trace and the thresholds for plotting).
    # We'll call engine.detect() to get carriers, but we also want to access
    # the smoothed trace, noise, etc. For simplicity we re-run the beginning.
    amp = np.asarray(amplitude, dtype=np.float64)
    window = engine._window_for(amp.size)
    core_trace = CarrierDetectionEngine._moving_average(amp, window)
    noise, noise_sigma = CarrierDetectionEngine._noise_statistics(core_trace)

    enter_level = noise + max(engine.enter_threshold_db, 6.0 * noise_sigma)
    exit_level = noise + max(engine.exit_threshold_db, 3.0 * noise_sigma)

    # Full detection
    carriers = engine.detect(amplitude)

    # Plot
    bins = np.arange(num_bins)

    plt.figure(figsize=(12, 6))
    plt.plot(bins, amplitude, alpha=0.5, label="Original spectrum (unsmoothed)")
    plt.plot(bins, core_trace, 'k', linewidth=1.2, label="Smoothed trace (core_trace)")

    # Threshold lines
    plt.axhline(y=noise, color='grey', linestyle='--', linewidth=1,
                label=f"Noise floor = {noise:.1f} dB")
    plt.axhline(y=enter_level, color='red', linestyle='-', linewidth=1.2,
                label=f"Enter threshold = {enter_level:.1f} dB (noise + max(enter_db, 6σ))")
    plt.axhline(y=exit_level, color='orange', linestyle='-', linewidth=1.2,
                label=f"Exit threshold = {exit_level:.1f} dB (noise + max(exit_db, 3σ))")

    # Shade detected carrier regions
    ymin, ymax = plt.ylim()
    for region in carriers:
        plt.axvspan(region.left_bin, region.right_bin, facecolor='green', alpha=0.15)
        # mark center
        plt.axvline(x=region.center_bin, color='darkgreen', linestyle=':', linewidth=1)

    plt.xlabel("Frequency bin")
    plt.ylabel("Amplitude (dB)")
    plt.title("Carrier Detection Thresholds and Detected Regions")
    plt.legend(loc='upper right', fontsize='small')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
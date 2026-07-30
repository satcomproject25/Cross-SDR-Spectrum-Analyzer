"""
carrier_detection.py

SATCOM Carrier Detection and Measurement Engine
===============================================

Phase 1 (retained):
- Smooth FFT spectrum
- Estimate noise floor
- Detect occupied carrier envelopes with hysteresis
- Reject narrow features

Phase 2 (this file):
- Adaptive rolling-median baseline (block-decimated, Pi-friendly)
- MAD-based adaptive thresholds
- Vectorised hysteresis via binary_propagation
- Morphological closing (bridge intra-carrier notches)
- Morphological opening (reject spurs by physical bandwidth, not bin count)
- Per-carrier 99 % occupied bandwidth (ITU-R SM.443 style)
- Per-carrier centre frequency
- Per-carrier integrated band power, noise-subtracted and ENBW-corrected

Contract note: left_bin / right_bin are preserved because frontend/renderer.py
draws the carrier fill overlay from them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

# Standard deviation of a single-look exponential power sample expressed in dB.
# Used only when the MAD estimate collapses (e.g. a heavily averaged trace).
DB_NOISE_SIGMA_FALLBACK = 5.57
MAD_TO_SIGMA = 1.4826

# Equivalent noise bandwidth of the Hann window, in FFT bins.
# Required because dBFS/dBm calibration is done with a CW tone (coherent gain),
# while a modulated carrier is integrated across many bins.
HANN_ENBW_BINS = 1.5


def _runs(mask: np.ndarray):
    """Start (inclusive) and stop (exclusive) indices of every True run."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.diff(padded.astype(np.int8))
    return np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)


def _close_runs(starts: np.ndarray, stops: np.ndarray, gap_bins: int):
    """Merge runs separated by fewer than gap_bins zeros.

    Equivalent to a 1-D binary closing with a flat structuring element of
    length gap_bins, but O(number of runs) instead of O(N * gap_bins).
    """
    if starts.size < 2 or gap_bins < 2:
        return starts, stops
    gaps = starts[1:] - stops[:-1]
    breaks = np.flatnonzero(gaps >= gap_bins)
    new_starts = np.concatenate(([starts[0]], starts[breaks + 1]))
    new_stops = np.concatenate((stops[breaks], [stops[-1]]))
    return new_starts, new_stops


@dataclass(slots=True)
class CarrierRegion:
    """One detected carrier: envelope bins plus derived measurements."""

    # Envelope (consumed by renderer.py for the fill overlay)
    left_bin: int
    right_bin: int
    center_bin: int
    peak_bin: int
    peak_power: float          # dBFS or dBm, same unit as the input trace
    noise_floor: float         # local baseline under this carrier
    confidence: float = 1.0

    # Measurements (Phase 2)
    center_frequency: float = 0.0      # Hz, midpoint of the 99 % power interval
    occupied_bandwidth: float = 0.0    # Hz, 0.5 % .. 99.5 % cumulative power
    band_power: float = 0.0            # dB, noise-subtracted, ENBW-corrected
    peak_frequency: float = 0.0        # Hz
    snr_db: float = 0.0                # peak above local baseline
    obw_left_bin: int = 0
    obw_right_bin: int = 0
    label: str = ""                    # filled by CarrierTracker ("C1", "C2", ...)


class CarrierDetectionEngine:
    """Detects carriers and measures each one independently.

    All bandwidth-like parameters are specified in Hz so that the behaviour does
    not change when the sample rate changes. They are converted to bins with the
    RBW supplied per frame.
    """

    def __init__(
        self,
        enter_threshold_db: float = 6.0,
        exit_threshold_db: float = 3.5,
        enter_sigma: float = 4.0,
        exit_sigma: float = 2.0,
        min_carrier_bw_hz: float = 0.8e6,
        max_notch_bw_hz: float = 0.30e6,
        smoothing_bw_hz: float = 0.05e6,
        spur_median_bins: int = 5,
        baseline_block_bins: int = 32,
        baseline_window_bins: int = 2048,
        max_baseline_tilt_db: float = 6.0,
        analysis_guard_hz: float = 0.20e6,
        obw_fraction: float = 0.99,
        window_enbw_bins: float = HANN_ENBW_BINS,
        max_carriers: int = 32,
    ):
        # Threshold offsets are the larger of a fixed dB margin and an adaptive
        # k-sigma margin, so the detector survives both a quiet noise floor and
        # a noisy one without retuning.
        self.enter_threshold_db = enter_threshold_db
        self.exit_threshold_db = exit_threshold_db
        self.enter_sigma = enter_sigma
        self.exit_sigma = exit_sigma

        self.min_carrier_bw_hz = min_carrier_bw_hz
        self.max_notch_bw_hz = max_notch_bw_hz
        self.smoothing_bw_hz = smoothing_bw_hz
        self.spur_median_bins = int(spur_median_bins)

        self.baseline_block_bins = int(baseline_block_bins)
        self.baseline_window_bins = int(baseline_window_bins)
        self.max_baseline_tilt_db = float(max_baseline_tilt_db)

        self.analysis_guard_hz = analysis_guard_hz
        self.obw_fraction = obw_fraction
        self.window_enbw_bins = float(window_enbw_bins)
        self.max_carriers = int(max_carriers)

        self._baseline = None  # last baseline, exposed for plotting/debug

    # ------------------------------------------------------------------
    # Baseline and threshold estimation
    # ------------------------------------------------------------------
    def estimate_baseline(self, spectrum: np.ndarray) -> np.ndarray:
        """Rolling-median noise baseline, block-decimated for speed.

        A median tolerates up to 50 % contamination, so the rolling window must
        be at least twice the widest expected carrier for the baseline not to be
        pulled up into the signal.
        """
        n = spectrum.size
        block = max(1, self.baseline_block_bins)
        usable = (n // block) * block
        if usable < 2 * block:
            return np.full(n, float(np.median(spectrum)), dtype=np.float64)

        blocks = spectrum[:usable].reshape(-1, block)
        coarse = np.median(blocks, axis=1)

        window = max(3, int(round(self.baseline_window_bins / block)))
        if window % 2 == 0:
            window += 1
        window = min(window, coarse.size if coarse.size % 2 else coarse.size - 1)
        if window >= 3:
            smoothed = median_filter(coarse, size=window, mode="nearest")
        else:
            smoothed = coarse

        # Guard against a wide carrier occupying more than half the rolling
        # window, which would drag the baseline up into the signal and hide the
        # carrier completely. The clamp allows genuine receiver tilt up to
        # max_baseline_tilt_db above the global robust floor, and no more.
        floor = float(np.percentile(coarse, 10.0))
        np.minimum(smoothed, floor + self.max_baseline_tilt_db, out=smoothed)

        coarse_x = (np.arange(smoothed.size) + 0.5) * block
        return np.interp(np.arange(n), coarse_x, smoothed)

    @staticmethod
    def estimate_sigma(residual: np.ndarray) -> float:
        """Robust noise spread in dB from the median absolute deviation."""
        mad = float(np.median(np.abs(residual - np.median(residual))))
        sigma = MAD_TO_SIGMA * mad
        if not np.isfinite(sigma) or sigma <= 0.05:
            sigma = DB_NOISE_SIGMA_FALLBACK
        return sigma

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect(
        self,
        amplitude: np.ndarray,
        frequency: np.ndarray | None = None,
        rbw: float | None = None,
    ) -> list[CarrierRegion]:
        raw = np.asarray(amplitude, dtype=np.float64)
        n = raw.size
        if n < 16:
            return []

        if frequency is None:
            frequency = np.arange(n, dtype=np.float64)
        else:
            frequency = np.asarray(frequency, dtype=np.float64)

        if rbw is None or rbw <= 0.0:
            rbw = float(abs(frequency[1] - frequency[0])) if n > 1 else 1.0
        bin_hz = max(rbw, 1e-9)

        def to_bins(hz: float, minimum: int = 1) -> int:
            return max(minimum, int(round(hz / bin_hz)))

        # --- 1. Detection trace ------------------------------------------
        # Smoothing is used ONLY to build the detection mask. Every power
        # measurement below uses the raw trace, because smoothing in the dB
        # domain is not power preserving.
        detect_trace = raw
        if self.spur_median_bins >= 3:
            detect_trace = median_filter(
                detect_trace, size=self.spur_median_bins | 1, mode="nearest"
            )
        smooth_bins = to_bins(self.smoothing_bw_hz)
        if smooth_bins >= 2:
            detect_trace = uniform_filter1d(detect_trace, size=smooth_bins, mode="nearest")

        # --- 2. Adaptive baseline and thresholds --------------------------
        baseline = self.estimate_baseline(detect_trace)
        self._baseline = baseline
        residual = detect_trace - baseline
        sigma = self.estimate_sigma(residual[residual < np.percentile(residual, 90)])

        enter_offset = max(self.enter_threshold_db, self.enter_sigma * sigma)
        exit_offset = max(self.exit_threshold_db, self.exit_sigma * sigma)
        if exit_offset >= enter_offset:
            exit_offset = 0.6 * enter_offset

        # --- 3. Hysteresis (run-length, O(N)) ------------------------------
        high = residual >= enter_offset
        if not high.any():
            return []
        low = residual >= exit_offset

        starts, stops = _runs(low)
        if starts.size == 0:
            return []
        seeded = np.cumsum(high)
        seeded = np.concatenate(([0], seeded))
        keep = (seeded[stops] - seeded[starts]) > 0
        starts, stops = starts[keep], stops[keep]
        if starts.size == 0:
            return []

        # --- 4. Morphological cleanup (run-length equivalent) --------------
        # Closing first: bridge intra-carrier notches (pilot gaps, interference
        # nulls, fading dropouts) so one carrier is not reported as two.
        notch_bins = to_bins(self.max_notch_bw_hz)
        starts, stops = _close_runs(starts, stops, notch_bins)
        # Then opening: delete anything narrower than a legitimate carrier.
        # This is the spur rejection stage, expressed in Hz rather than bins.
        min_bins = to_bins(self.min_carrier_bw_hz, minimum=3)
        widths = stops - starts
        keep = widths >= min_bins
        starts, stops = starts[keep], stops[keep]
        if starts.size == 0:
            return []

        # --- 5. Per-carrier measurement -----------------------------------
        power_lin = np.power(10.0, raw / 10.0)
        noise_lin = np.power(10.0, baseline / 10.0)
        guard = to_bins(self.analysis_guard_hz, minimum=1)

        regions: list[CarrierRegion] = []
        for start, stop in zip(starts[: self.max_carriers], stops[: self.max_carriers]):
            left, right = int(start), int(stop) - 1
            region = self._measure(
                left, right, guard, raw, power_lin, noise_lin, baseline, frequency, bin_hz, n
            )
            if region is not None:
                regions.append(region)

        return regions

    # ------------------------------------------------------------------
    def _measure(
        self, left, right, guard, raw, power_lin, noise_lin, baseline, frequency, bin_hz, n
    ) -> CarrierRegion | None:
        # The hysteresis exit threshold truncates the carrier skirts, which
        # biases a 99 % power measurement low. Re-open the window by a guard
        # band before integrating.
        a = max(0, left - guard)
        b = min(n - 1, right + guard)

        seg = power_lin[a : b + 1]
        seg_noise = noise_lin[a : b + 1]
        net = np.maximum(seg - seg_noise, 0.0)
        total = float(net.sum())
        if total <= 0.0:
            return None

        # 99 % occupied bandwidth on the noise-subtracted power density.
        # Subtracting the pedestal first is what stops a weak carrier from
        # reporting an absurdly wide OBW.
        tail = 0.5 * (1.0 - self.obw_fraction)
        cumulative = np.cumsum(net)
        lo = int(np.searchsorted(cumulative, total * tail))
        hi = int(np.searchsorted(cumulative, total * (1.0 - tail)))
        lo = min(max(lo, 0), net.size - 1)
        hi = min(max(hi, lo), net.size - 1)

        obw_left = a + lo
        obw_right = a + hi
        f_lo = float(frequency[obw_left])
        f_hi = float(frequency[obw_right])
        occupied_bandwidth = max(0.0, f_hi - f_lo) + bin_hz
        center_frequency = 0.5 * (f_lo + f_hi)

        # Integrated band power over the occupied bandwidth only.
        # Divide by the window ENBW: the per-bin calibration is coherent (CW),
        # so summing bins of a modulated signal overstates power by ENBW.
        band_lin = float(np.sum(net[lo : hi + 1])) / max(self.window_enbw_bins, 1e-6)
        band_power = 10.0 * np.log10(max(band_lin, 1e-30))

        peak_bin = int(a + np.argmax(raw[a : b + 1]))
        local_noise = float(np.median(baseline[a : b + 1]))
        peak_power = float(raw[peak_bin])

        return CarrierRegion(
            left_bin=int(left),
            right_bin=int(right),
            center_bin=int(round(0.5 * (obw_left + obw_right))),
            peak_bin=peak_bin,
            peak_power=peak_power,
            noise_floor=local_noise,
            confidence=1.0,
            center_frequency=center_frequency,
            occupied_bandwidth=occupied_bandwidth,
            band_power=band_power,
            peak_frequency=float(frequency[peak_bin]),
            snr_db=peak_power - local_noise,
            obw_left_bin=int(obw_left),
            obw_right_bin=int(obw_right),
        )
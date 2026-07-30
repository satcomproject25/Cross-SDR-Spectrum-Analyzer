"""
carrier_measure.py

Per-carrier measurement and tracking layer.

This module is strictly additive: it consumes the CarrierRegion objects produced
by CarrierDetectionEngine.detect() and derives the quantities needed for a
carrier table. carrier_detection.py is not modified and not imported here, so
detection behaviour is unchanged.

Produced per carrier:
    centre frequency      midpoint of the 99 % power interval
    occupied bandwidth    ITU-R SM.443 style, on noise-subtracted power density
    band power            integrated over the OBW, noise-subtracted,
                          window-ENBW corrected

Design notes
------------
1. The detector aligns left_bin/right_bin to an exit-threshold crossing roughly
   3 dB above the floor, so the carrier skirts sit outside those bins. A 99 %
   power measurement must re-open the window by a guard band or it reads low.

2. The detector supplies one scalar noise_floor per frame. Over a wide span with
   receiver tilt, or across the 2150-2175 MHz HackRF path step, that scalar is
   not the local pedestal under a given carrier. This layer measures the local
   floor from shoulder windows either side of each carrier and interpolates
   across it, falling back to region.noise_floor when no clean shoulder exists.

3. All power arithmetic uses the raw, unsmoothed trace. The detector's moving
   average operates in the dB domain and is not power preserving.

4. The dBFS/dBm calibration is derived from CW tones (coherent window gain), so
   integrating a modulated carrier across many bins overstates power by the
   window ENBW. Hann ENBW is 1.5 bins => 1.76 dB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

HANN_ENBW_BINS = 1.5

# Median of an exponentially distributed power sample is ln(2) x its mean, i.e.
# 1.59 dB low. The pedestal we subtract must be a mean power, so the median-based
# shoulder estimate is corrected by this amount. Set to 0.0 when measuring a
# heavily averaged trace, where the median converges on the mean.
MEDIAN_TO_MEAN_DB = 1.5917


@dataclass(slots=True)
class CarrierMeasurement:
    """A detected carrier plus its measurements.

    The envelope fields are copied verbatim from CarrierRegion so that existing
    consumers (renderer.py carrier fill overlay) work unchanged.
    """

    # --- copied from CarrierRegion ---
    left_bin: int
    right_bin: int
    center_bin: int
    peak_bin: int
    peak_power: float
    noise_floor: float
    confidence: float

    # --- measurements ---
    center_frequency: float
    occupied_bandwidth: float
    band_power: float
    peak_frequency: float
    snr_db: float
    obw_left_bin: int
    obw_right_bin: int
    local_noise_floor: float

    label: str = ""


class CarrierMeasurementEngine:
    def __init__(
        self,
        obw_fraction: float = 0.99,
        window_enbw_bins: float = HANN_ENBW_BINS,
        analysis_guard_hz: float = 0.20e6,
        noise_gap_hz: float = 0.05e6,
        noise_window_hz: float = 0.30e6,
        median_to_mean_db: float = MEDIAN_TO_MEAN_DB,
        min_carrier_bw_hz: float = 0.0,
        max_carriers: int = 32,
    ):
        """
        obw_fraction       fraction of in-band power bounded by the OBW (0.99)
        analysis_guard_hz  skirt margin re-added outside the detected edges
        noise_gap_hz       dead zone next to each edge, excluded from the
                           shoulder estimate so skirt energy is not counted
                           as noise
        noise_window_hz    width of each shoulder window
        min_carrier_bw_hz  discard carriers whose measured OBW is below this.
                           0.0 keeps detector behaviour exactly as-is; set to
                           0.8e6 to enforce the modem-carrier spur rule.
        """
        self.obw_fraction = float(obw_fraction)
        self.window_enbw_bins = float(window_enbw_bins)
        self.analysis_guard_hz = float(analysis_guard_hz)
        self.noise_gap_hz = float(noise_gap_hz)
        self.noise_window_hz = float(noise_window_hz)
        self.median_to_mean_db = float(median_to_mean_db)
        self.min_carrier_bw_hz = float(min_carrier_bw_hz)
        self.max_carriers = int(max_carriers)

    # ------------------------------------------------------------------
    def measure(
        self,
        regions,
        amplitude: np.ndarray,
        frequency: np.ndarray,
        rbw: float | None = None,
    ) -> list[CarrierMeasurement]:
        if not regions:
            return []

        raw = np.asarray(amplitude, dtype=np.float64)
        freq = np.asarray(frequency, dtype=np.float64)
        n = raw.size
        if n < 8 or freq.size != n:
            return []

        if rbw is None or rbw <= 0.0:
            rbw = float(abs(freq[1] - freq[0])) if n > 1 else 1.0
        bin_hz = max(float(rbw), 1e-9)

        def to_bins(hz: float, minimum: int = 1) -> int:
            return max(minimum, int(round(hz / bin_hz)))

        guard = to_bins(self.analysis_guard_hz)
        noise_gap = to_bins(self.noise_gap_hz)
        noise_window = to_bins(self.noise_window_hz, minimum=4)

        # Regions arrive sorted by left_bin. Neighbour bounds stop a guard band
        # or a shoulder window from reaching into the adjacent carrier.
        ordered = sorted(regions, key=lambda r: r.left_bin)[: self.max_carriers]
        power_lin = np.power(10.0, raw / 10.0)

        results: list[CarrierMeasurement] = []
        for index, region in enumerate(ordered):
            previous = ordered[index - 1] if index > 0 else None
            following = ordered[index + 1] if index + 1 < len(ordered) else None
            lower_limit = 0 if previous is None else previous.right_bin + 1
            upper_limit = n - 1 if following is None else following.left_bin - 1

            measurement = self._measure_one(
                region,
                raw,
                power_lin,
                freq,
                bin_hz,
                guard,
                noise_gap,
                noise_window,
                lower_limit,
                upper_limit,
            )
            if measurement is None:
                continue
            if measurement.occupied_bandwidth < self.min_carrier_bw_hz:
                continue
            results.append(measurement)

        return results

    # ------------------------------------------------------------------
    def _local_noise(
        self,
        region,
        raw: np.ndarray,
        noise_gap: int,
        noise_window: int,
        lower_limit: int,
        upper_limit: int,
    ) -> tuple[float, float]:
        """Median floor in the left and right shoulder windows, in dB."""
        left_stop = region.left_bin - noise_gap
        left_start = max(lower_limit, left_stop - noise_window)
        right_start = region.right_bin + noise_gap
        right_stop = min(upper_limit, right_start + noise_window)

        left_level = right_level = None
        if left_stop - left_start >= 4:
            left_level = float(np.median(raw[left_start:left_stop]))
        if right_stop - right_start >= 4:
            right_level = float(np.median(raw[right_start:right_stop]))

        if left_level is None and right_level is None:
            # No clean shoulder: fall back to the detector's frame-wide floor.
            return region.noise_floor, region.noise_floor
        if left_level is None:
            left_level = right_level
        if right_level is None:
            right_level = left_level

        correction = self.median_to_mean_db
        return left_level + correction, right_level + correction

    # ------------------------------------------------------------------
    def _measure_one(
        self,
        region,
        raw: np.ndarray,
        power_lin: np.ndarray,
        freq: np.ndarray,
        bin_hz: float,
        guard: int,
        noise_gap: int,
        noise_window: int,
        lower_limit: int,
        upper_limit: int,
    ) -> CarrierMeasurement | None:
        # Analysis window: detected envelope plus a skirt guard, clipped so it
        # never crosses into a neighbouring carrier.
        start = max(lower_limit, region.left_bin - guard)
        stop = min(upper_limit, region.right_bin + guard)
        if stop - start < 4:
            return None

        left_level, right_level = self._local_noise(
            region, raw, noise_gap, noise_window, lower_limit, upper_limit
        )

        # Linear ramp between the two shoulder levels handles receiver tilt and
        # the HackRF path step without assuming a flat pedestal.
        span = stop - start
        pedestal_db = left_level + (right_level - left_level) * (
            np.arange(span + 1, dtype=np.float64) / max(span, 1)
        )
        pedestal_lin = np.power(10.0, pedestal_db / 10.0)

        net = np.maximum(power_lin[start : stop + 1] - pedestal_lin, 0.0)
        total = float(net.sum())
        if total <= 0.0:
            return None

        tail = 0.5 * (1.0 - self.obw_fraction)
        cumulative = np.cumsum(net)
        low = int(np.searchsorted(cumulative, total * tail))
        high = int(np.searchsorted(cumulative, total * (1.0 - tail)))
        low = min(max(low, 0), net.size - 1)
        high = min(max(high, low), net.size - 1)

        obw_left = start + low
        obw_right = start + high
        f_low = float(freq[obw_left])
        f_high = float(freq[obw_right])

        # + one bin: the interval spans (high - low + 1) bins of width RBW.
        occupied_bandwidth = max(0.0, f_high - f_low) + bin_hz
        center_frequency = 0.5 * (f_low + f_high)

        band_lin = float(net[low : high + 1].sum()) / max(self.window_enbw_bins, 1e-6)
        band_power = 10.0 * np.log10(max(band_lin, 1e-30))

        local_floor = 0.5 * (left_level + right_level)

        return CarrierMeasurement(
            left_bin=int(region.left_bin),
            right_bin=int(region.right_bin),
            center_bin=int(round(0.5 * (obw_left + obw_right))),
            peak_bin=int(region.peak_bin),
            peak_power=float(region.peak_power),
            noise_floor=float(region.noise_floor),
            confidence=float(region.confidence),
            center_frequency=center_frequency,
            occupied_bandwidth=occupied_bandwidth,
            band_power=band_power,
            peak_frequency=float(freq[int(region.peak_bin)]),
            snr_db=float(region.peak_power) - local_floor,
            obw_left_bin=int(obw_left),
            obw_right_bin=int(obw_right),
            local_noise_floor=local_floor,
        )


# ---------------------------------------------------------------------------
# Frame-to-frame association
#
# Without this stage the table is unusable: each FFT frame yields an
# independent detection list, so rows renumber and vanish at the frame rate
# and every value jitters by the full single-look noise spread.
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CarrierTrack:
    id: int
    label: str
    center_frequency: float
    occupied_bandwidth: float
    band_power: float
    peak_frequency: float
    peak_power: float
    snr_db: float
    left_bin: int
    right_bin: int
    hits: int = 0
    misses: int = 0
    age: int = 0
    confirmed: bool = False
    confidence: float = 0.0
    # Filled by controller.py after tracking, so the table can show whichever
    # unit is valid without the tracker needing to know about calibration.
    band_power_dbfs: float = 0.0
    band_power_dbm: float | None = None
    _power_lin: float = field(default=0.0, repr=False)


class CarrierTracker:
    def __init__(
        self,
        confirm_frames: int = 3,
        drop_frames: int = 8,
        match_tolerance_bw_fraction: float = 0.35,
        match_tolerance_min_bins: float = 4.0,
        alpha: float = 0.25,
    ):
        self.confirm_frames = confirm_frames
        self.drop_frames = drop_frames
        self.match_tolerance_bw_fraction = match_tolerance_bw_fraction
        self.match_tolerance_min_bins = match_tolerance_min_bins
        self.alpha = alpha
        self._tracks: list[CarrierTrack] = []
        self._next_id = 1

    def reset(self):
        self._tracks.clear()
        self._next_id = 1

    def update(self, regions, rbw: float) -> list[CarrierTrack]:
        unmatched = list(regions)
        a = self.alpha

        for track in self._tracks:
            track.age += 1
            tolerance = max(
                self.match_tolerance_bw_fraction * track.occupied_bandwidth,
                self.match_tolerance_min_bins * max(rbw, 1e-9),
            )
            best, best_delta = None, tolerance
            for region in unmatched:
                delta = abs(region.center_frequency - track.center_frequency)
                if delta <= best_delta:
                    best, best_delta = region, delta

            if best is None:
                track.misses += 1
                continue

            unmatched.remove(best)
            track.hits += 1
            track.misses = 0
            track.center_frequency += a * (best.center_frequency - track.center_frequency)
            track.occupied_bandwidth += a * (
                best.occupied_bandwidth - track.occupied_bandwidth
            )
            # Power is averaged linearly, then converted back to dB.
            track._power_lin += a * (10.0 ** (best.band_power / 10.0) - track._power_lin)
            track.band_power = 10.0 * np.log10(max(track._power_lin, 1e-30))
            track.peak_frequency = best.peak_frequency
            track.peak_power = best.peak_power
            track.snr_db += a * (best.snr_db - track.snr_db)
            track.left_bin = best.left_bin
            track.right_bin = best.right_bin
            if track.hits >= self.confirm_frames:
                track.confirmed = True
            track.confidence = min(1.0, track.hits / max(self.confirm_frames, 1))

        for region in unmatched:
            self._tracks.append(
                CarrierTrack(
                    id=self._next_id,
                    label=f"C{self._next_id}",
                    center_frequency=region.center_frequency,
                    occupied_bandwidth=region.occupied_bandwidth,
                    band_power=region.band_power,
                    peak_frequency=region.peak_frequency,
                    peak_power=region.peak_power,
                    snr_db=region.snr_db,
                    left_bin=region.left_bin,
                    right_bin=region.right_bin,
                    hits=1,
                    confirmed=self.confirm_frames <= 1,
                    confidence=1.0 / max(self.confirm_frames, 1),
                    _power_lin=10.0 ** (region.band_power / 10.0),
                )
            )
            self._next_id += 1

        self._tracks = [t for t in self._tracks if t.misses < self.drop_frames]
        published = [t for t in self._tracks if t.confirmed]
        published.sort(key=lambda t: t.center_frequency)
        return published
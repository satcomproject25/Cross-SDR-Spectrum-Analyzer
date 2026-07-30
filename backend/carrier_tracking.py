"""
carrier_tracking.py

Frame-to-frame association for detected carriers.

Without this stage the table is unusable: every FFT frame produces an
independent detection list, so rows appear, vanish and renumber at the frame
rate, and every value jitters by the full single-look noise spread.

Provides:
- stable identities (C1, C2, ...) matched by centre frequency
- M-of-N confirmation before a carrier is published (false-alarm suppression)
- miss tolerance before a carrier is dropped (fade / low-SNR recovery)
- exponential smoothing of reported values, power averaged in the linear domain
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


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
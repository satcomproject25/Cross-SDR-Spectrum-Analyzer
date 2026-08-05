import numpy as np

from .dsp import SPECTRUM_FLOOR_DBFS
from .models import TraceData


MIN_HOLD_FLOOR_GUARD_DB = 1.0


class TraceEngine:
    def __init__(self):
        self.clear()

    def update(self, spectrum):
        live = np.asarray(spectrum.amplitude, dtype=np.float32).copy()
        live_power = np.power(10.0, live.astype(np.float64) / 10.0)
        if self.max_hold is None or self.max_hold.shape != live.shape:
            self.max_hold = live.copy()
            self.average_power = live_power
            self.frames = 1
        else:
            np.maximum(self.max_hold, live, out=self.max_hold)
            self.average_power += (
                live_power - self.average_power
            ) / (self.frames + 1)
            self.frames += 1

        # Spectrum averaging is a power detector: average linear bin power,
        # then convert the displayed result back to dBFS. Averaging dB values
        # directly suppresses noise-like QPSK/OFDM carriers.
        average = 10.0 * np.log10(np.maximum(self.average_power, 1e-24))

        # Values at the DSP clamp are numerical underflow/cancellation, not a
        # measurable receiver level. Letting one such value into a persistent
        # minimum pins that bin to -140 dBFS forever.
        valid_min = np.isfinite(live) & (
            live > SPECTRUM_FLOOR_DBFS + MIN_HOLD_FLOOR_GUARD_DB
        )
        if self.min_hold is None or self.min_hold.shape != live.shape:
            if np.any(valid_min):
                fallback = float(np.median(live[valid_min]))
                self.min_hold = np.where(valid_min, live, fallback).astype(np.float32)
            else:
                self.min_hold = live.copy()
        else:
            candidates = np.where(valid_min, live, np.inf)
            np.minimum(self.min_hold, candidates, out=self.min_hold)

        return TraceData(
            frequency=spectrum.frequency,
            live=live,
            max_hold=self.max_hold.copy(),
            min_hold=self.min_hold.copy(),
            average=average.astype(np.float32, copy=False),
            frame_count=self.frames,
        )

    def clear(self):
        self.max_hold = None
        self.min_hold = None
        self.average_power = None
        self.frames = 0

    def reset_min_hold(self):
        """Start a new minimum acquisition without resetting other traces."""
        self.min_hold = None

import numpy as np

from .models import TraceData


class TraceEngine:
    def __init__(self):
        self.clear()

    def update(self, spectrum):
        live = np.asarray(spectrum.amplitude, dtype=np.float32).copy()
        if self.max_hold is None or self.max_hold.shape != live.shape:
            self.max_hold = live.copy()
            self.min_hold = live.copy()
            self.average = live.copy()
            self.frames = 1
        else:
            np.maximum(self.max_hold, live, out=self.max_hold)
            np.minimum(self.min_hold, live, out=self.min_hold)
            self.average += (live - self.average) / (self.frames + 1)
            self.frames += 1

        return TraceData(
            frequency=spectrum.frequency,
            live=live,
            max_hold=self.max_hold.copy(),
            min_hold=self.min_hold.copy(),
            average=self.average.copy(),
            frame_count=self.frames,
        )

    def clear(self):
        self.max_hold = None
        self.min_hold = None
        self.average = None
        self.frames = 0

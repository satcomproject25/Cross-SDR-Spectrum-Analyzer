import numpy as np

from .models import Peak


class PeakEngine:
    def __init__(self, number_of_peaks: int = 10, threshold_db: float = 6.0):
        self.number_of_peaks = number_of_peaks
        self.threshold_db = threshold_db

    def find(self, traces) -> list[Peak]:
        amplitude = np.asarray(traces.live)
        frequency = np.asarray(traces.frequency)
        if amplitude.size < 3:
            return []

        threshold = float(np.median(amplitude) + self.threshold_db)
        candidates = np.flatnonzero(
            (amplitude[1:-1] > amplitude[:-2])
            & (amplitude[1:-1] >= amplitude[2:])
            & (amplitude[1:-1] >= threshold)
        ) + 1
        candidates = candidates[np.argsort(amplitude[candidates])[::-1]]

        # Keep separate signals apart by roughly 1% of the displayed FFT bins.
        guard_bins = max(3, amplitude.size // 100)
        accepted: list[int] = []
        for index in candidates:
            index = int(index)
            if any(abs(index - other) < guard_bins for other in accepted):
                continue
            accepted.append(index)
            if len(accepted) >= self.number_of_peaks:
                break

        return [
            Peak(i + 1, float(frequency[index]), float(amplitude[index]), index)
            for i, index in enumerate(accepted)
        ]

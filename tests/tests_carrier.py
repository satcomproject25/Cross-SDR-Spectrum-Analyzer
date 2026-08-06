import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np
from backend.carrier_detection import CarrierDetectionEngine
from backend.carrier_tracking import CarrierTracker

FFT, FS, FC = 4096, 20e6, 2440e6
RBW = FS / FFT
FREQ = FC + (np.arange(FFT) - FFT // 2) * RBW


def _frame(rng):
    p = 10 ** (-100 / 10) * rng.exponential(1.0, FFT)
    for cf, bw, dbm in ((2437e6, 3.0e6, -40), (2443.5e6, 1.2e6, -55)):
        m = np.abs(FREQ - cf) < bw / 2
        p[m] += 10 ** (dbm / 10) / m.sum() * rng.exponential(1.0, m.sum()) * 1.5
    p[np.abs(FREQ - 2437.6e6) < 0.15e6] *= 0.02          # intra-carrier notch
    p[int(np.argmin(np.abs(FREQ - 2441.7e6)))] += 10 ** (-45 / 10)   # spur
    return 10 * np.log10(p)


def test_two_carriers_one_spur():
    rng = np.random.default_rng(7)
    detector, tracker = CarrierDetectionEngine(), CarrierTracker()
    tracks = []
    for _ in range(20):
        tracks = tracker.update(detector.detect(_frame(rng), FREQ, RBW), RBW)

    assert len(tracks) == 2, [t.label for t in tracks]
    assert abs(tracks[0].center_frequency - 2437e6) < 2 * RBW
    assert abs(tracks[1].center_frequency - 2443.5e6) < 2 * RBW
    assert abs(tracks[0].occupied_bandwidth - 3.0e6) < 0.15e6
    assert abs(tracks[0].band_power - (-40)) < 1.5


def test_termination_produces_no_rows():
    rng = np.random.default_rng(3)
    detector = CarrierDetectionEngine()
    for _ in range(30):
        noise = 10 * np.log10(10 ** (-100 / 10) * rng.exponential(1.0, FFT))
        assert detector.detect(noise, FREQ, RBW) == []
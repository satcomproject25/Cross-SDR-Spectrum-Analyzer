"""FFT processing for complex, normalized SDR samples."""

import numpy as np

from .models import SpectrumData

SPECTRUM_FLOOR_DBFS = -140.0


class DSPEngine:
    def __init__(self, fft_size: int = 4096):
        if fft_size < 256 or fft_size & (fft_size - 1):
            raise ValueError("fft_size must be a power of two and at least 256")
        self.fft_size = fft_size
        self.window = np.hanning(fft_size).astype(np.float32)
        self.coherent_gain = float(np.sum(self.window))

    def process(self, frame, display_span: float | None = None) -> SpectrumData:
        samples = np.asarray(frame.samples, dtype=np.complex64)
        samples = samples - np.mean(samples)                               # DC blocker
        if samples.size != self.fft_size:
            raise ValueError(
                f"Expected {self.fft_size} IQ samples, received {samples.size}"
            )

        fft = np.fft.fftshift(np.fft.fft(samples * self.window))
        # With normalized CF32 samples this is dBFS, not calibrated dBm.
        floor_linear = 10.0 ** (SPECTRUM_FLOOR_DBFS / 20.0)
        amplitude = 20.0 * np.log10(
            np.maximum(np.abs(fft) / self.coherent_gain, floor_linear)
        )
        frequency = frame.center_frequency + np.fft.fftshift(
            np.fft.fftfreq(self.fft_size, d=1.0 / frame.sample_rate)
        )

        span = min(float(display_span or frame.sample_rate), float(frame.sample_rate))
        if span < frame.sample_rate:
            half = span / 2.0
            mask = np.abs(frequency - frame.center_frequency) <= half
            frequency = frequency[mask]
            amplitude = amplitude[mask]

        return SpectrumData(
            frequency=frequency,
            amplitude=amplitude.astype(np.float32, copy=False),
            center_frequency=frame.center_frequency,
            span=span,
            sample_rate=frame.sample_rate,
            fft_size=self.fft_size,
            rbw=frame.sample_rate / self.fft_size,
        )

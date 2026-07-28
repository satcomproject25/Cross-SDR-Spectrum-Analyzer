"""Stateful DSP pipeline that turns IQ blocks into frontend frames."""

import time

from .dsp import DSPEngine
from .measurements import MeasurementEngine
from .models import IQFrame, SpectrumFrame
from .peak import PeakEngine
from .carrier_detection import CarrierDetectionEngine
from .trace import TraceEngine
from .power_calibration import dbfs_to_dbm


class AnalyzerPipeline:
    def __init__(self, config, device_name: str = "", power_offset_db=None):
        self.config = config
        self.device_name = device_name
        self.dsp = DSPEngine(config.fft_size)
        self.traces = TraceEngine()
        self.measurements = MeasurementEngine()
        self.peaks = PeakEngine()
        self.carrier_detector = CarrierDetectionEngine()
        self.frame_count = 0
        # dBFS -> dBm offset resolved once at bring-up (acquisition.py).
        # None => uncalibrated, values pass through unchanged and stay dBFS.
        self._power_offset_db = power_offset_db

    def process(self, samples) -> SpectrumFrame:
        iq_frame = IQFrame(
            samples=samples,
            frame_number=self.frame_count,
            sample_rate=self.config.sample_rate,
            center_frequency=self.config.center_frequency,
        )
        spectrum = self.dsp.process(iq_frame, self.config.span)

        # Convert the raw dBFS spectrum to dBm here, in one place, BEFORE any
        # trace/measurement consumes it. SpectrumData.amplitude is the dBFS
        # magnitude array (see dsp.py); a constant offset is safe to apply
        # before trace accumulation, and doing it here keeps live/hold/average
        # traces, peaks and measurements all in the same calibrated unit.
        # No-op when uncalibrated (offset is None).
        spectrum.amplitude = dbfs_to_dbm(spectrum.amplitude, self._power_offset_db)
        if self.frame_count == 0:
            print(f"[CAL] offset={self._power_offset_db}")
            print(f"[CAL] spectrum.amplitude max = {spectrum.amplitude.max():.2f}")
        traces = self.traces.update(spectrum)
        if self.frame_count == 0:
            print(f"[CAL] traces.live max = {traces.live.max():.2f}")

        traces = self.traces.update(spectrum)
        carriers = self.carrier_detector.detect(traces.live)
        measurements = self.measurements.update(traces)
        peaks = self.peaks.find(traces)
        if self.frame_count == 0:
            print(f"[CAL] measurements.peak/amp = {measurements.peak_amplitude:.2f}")
            print(f"[CAL] peaks = {peaks}")
        self.frame_count += 1
        return SpectrumFrame(
            frequency=traces.frequency,
            amplitude=traces.live,
            max_hold=traces.max_hold,
            min_hold=traces.min_hold,
            average=traces.average,
            peaks=peaks,
            bandwidth=measurements.occupied_bandwidth,
            timestamp=time.time(),
            noise_floor=measurements.noise_floor,
            channel_power=measurements.channel_power,
            center_frequency=spectrum.center_frequency,
            sample_rate=spectrum.sample_rate,
            span=spectrum.span,
            fft_size=spectrum.fft_size,
            rbw=spectrum.rbw,
            frame_count=traces.frame_count,
            device_name=self.device_name,
            unit=("dBm" if self._power_offset_db is not None else "dBFS"),
            carriers=carriers,
        )

    def clear_traces(self):
        self.traces.clear()
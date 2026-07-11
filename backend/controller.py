"""Stateful DSP pipeline that turns IQ blocks into frontend frames."""

import time

from .dsp import DSPEngine
from .measurements import MeasurementEngine
from .models import IQFrame, SpectrumFrame
from .peak import PeakEngine
from .trace import TraceEngine


class AnalyzerPipeline:
    def __init__(self, config, device_name: str = ""):
        self.config = config
        self.device_name = device_name
        self.dsp = DSPEngine(config.fft_size)
        self.traces = TraceEngine()
        self.measurements = MeasurementEngine()
        self.peaks = PeakEngine()
        self.frame_count = 0

    def process(self, samples) -> SpectrumFrame:
        iq_frame = IQFrame(
            samples=samples,
            frame_number=self.frame_count,
            sample_rate=self.config.sample_rate,
            center_frequency=self.config.center_frequency,
        )
        spectrum = self.dsp.process(iq_frame, self.config.span)
        traces = self.traces.update(spectrum)
        measurements = self.measurements.update(traces)
        peaks = self.peaks.find(traces)
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
            carrier_bandwidth=measurements.carrier_bandwidth,
            center_frequency=spectrum.center_frequency,
            sample_rate=spectrum.sample_rate,
            span=spectrum.span,
            fft_size=spectrum.fft_size,
            rbw=spectrum.rbw,
            frame_count=traces.frame_count,
            device_name=self.device_name,
        )

    def clear_traces(self):
        self.traces.clear()

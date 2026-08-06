"""Stateful DSP pipeline that turns IQ blocks into frontend frames."""

import time

from .dsp import DSPEngine
from .measurements import MeasurementEngine
from .models import IQFrame, SpectrumFrame
from .peak import PeakEngine
from .carrier_detection import CarrierDetectionEngine   
from .calibration import PowerCalibration
from .trace import TraceEngine


class AnalyzerPipeline:
    def __init__(self, config, device_name: str = "", serial: str = ""):
        self.config = config
        self.device_name = device_name
        self.serial = serial
        self.power_cal = PowerCalibration.for_device(config.device_type, serial)
        self.dsp = DSPEngine(config.fft_size)
        self.traces = TraceEngine()
        self.measurements = MeasurementEngine()
        self.peaks = PeakEngine()
        self.carrier_detector = CarrierDetectionEngine()
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
        carriers = self.carrier_detector.detect(
        traces.live
        )
        measurements = self.measurements.update(traces)
        peaks = self.peaks.find(traces)
        self.frame_count += 1

        # Traces stay in raw dBFS. The conversion travels alongside them so the
        # raw measurement and the calibration applied to it remain separable
        # and auditable all the way out to the CSV export.
        power_offset = self.power_cal.offset_db(
            spectrum.center_frequency, float(self.config.gain)
        )
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
            carriers=carriers,
            power_offset_db=power_offset,
            power_calibrated=self.power_cal.valid,
            power_in_cal_range=self.power_cal.in_range(spectrum.center_frequency),
        )

    def clear_traces(self):
        self.traces.clear()

    def reload_calibration(self, serial: str | None = None):
        """Re-read calibration.json without tearing down the DSP state.

        Note that the frequency axis offset is applied once at tune time inside
        the acquisition layer, so this refreshes POWER calibration only. A
        frequency recalibration still needs the stream restarted.
        """
        if serial is not None:
            self.serial = serial
        self.power_cal = PowerCalibration.for_device(
            self.config.device_type, self.serial
        )
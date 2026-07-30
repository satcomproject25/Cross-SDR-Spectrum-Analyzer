"""Stateful DSP pipeline that turns IQ blocks into frontend frames."""

import math
import time
import numpy as np

from .dsp import DSPEngine
from .measurements import MeasurementEngine
from .models import IQFrame, Peak, SpectrumFrame
from .peak import PeakEngine
from .carrier_detection import CarrierDetectionEngine
from .trace import TraceEngine
from .power_calibration import dbfs_to_dbm


class AnalyzerPipeline:
    def __init__(
        self,
        config,
        device_name: str = "",
        power_offset_db: float | None = None,
    ):
        self.config = config
        self.device_name = device_name
        try:
            offset = float(power_offset_db) if power_offset_db is not None else None
        except (TypeError, ValueError):
            offset = None
        self.power_offset_db = (
            offset if offset is not None and math.isfinite(offset) else None
        )
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
        carriers = self.carrier_detector.detect(traces.live)
        measurements = self.measurements.update(traces)
        peaks = self.peaks.find(traces)

        calibrated = self.power_offset_db is not None
        if calibrated:
            offset = self.power_offset_db
            amplitude_dbm = np.asarray(dbfs_to_dbm(traces.live, offset)).copy()
            max_hold_dbm = np.asarray(dbfs_to_dbm(traces.max_hold, offset)).copy()
            min_hold_dbm = np.asarray(dbfs_to_dbm(traces.min_hold, offset)).copy()
            average_dbm = np.asarray(dbfs_to_dbm(traces.average, offset)).copy()
            peaks_dbm = [
                Peak(
                    peak.id,
                    peak.frequency,
                    float(dbfs_to_dbm(peak.amplitude, offset)),
                    peak.bin_index,
                )
                for peak in peaks
            ]
            noise_floor_dbm = float(
                dbfs_to_dbm(measurements.noise_floor, offset)
            )
            channel_power_dbm = float(
                dbfs_to_dbm(measurements.channel_power, offset)
            )
        else:
            amplitude_dbm = None
            max_hold_dbm = None
            min_hold_dbm = None
            average_dbm = None
            peaks_dbm = []
            noise_floor_dbm = None
            channel_power_dbm = None

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
            unit="dBm" if calibrated else "dBFS",
            carriers=carriers,
            amplitude_dbfs=traces.live,
            max_hold_dbfs=traces.max_hold,
            min_hold_dbfs=traces.min_hold,
            average_dbfs=traces.average,
            amplitude_dbm=amplitude_dbm,
            max_hold_dbm=max_hold_dbm,
            min_hold_dbm=min_hold_dbm,
            average_dbm=average_dbm,
            peaks_dbm=peaks_dbm,
            noise_floor_dbfs=measurements.noise_floor,
            channel_power_dbfs=measurements.channel_power,
            noise_floor_dbm=noise_floor_dbm,
            channel_power_dbm=channel_power_dbm,
            power_offset_db=self.power_offset_db,
            power_calibrated=calibrated,
            amplitude_unit="dBm" if calibrated else "dBFS",
        )

    def clear_traces(self):
        self.traces.clear()
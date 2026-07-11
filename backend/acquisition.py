"""Continuous SDR acquisition through the vendor-neutral SoapySDR API."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from .controller import AnalyzerPipeline
from .models import AcquisitionConfig, DeviceInfo


DRIVER_NAMES = {
    "HACKRF": {"hackrf"},
    "USRP": {"uhd"},
    "PLUTO": {"plutosdr", "pluto"},
}


class AcquisitionError(RuntimeError):
    pass


def create_acquisition(config: AcquisitionConfig):
    if config.device_type.upper() == "SIMULATOR":
        return SyntheticAcquisition(config)
    return SoapyAcquisition(config)


class SyntheticAcquisition:
    """Phase-continuous IQ generator for testing the complete live pipeline."""

    def __init__(self, config: AcquisitionConfig, frame_rate: float = 30.0):
        self.config = config
        self.frame_rate = frame_rate
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(
        self,
        frame_callback: Callable[[object], None],
        status_callback: Callable[[str], None] | None = None,
    ):
        if status_callback:
            status_callback("Connected: Built-in IQ Simulator")
        pipeline = AnalyzerPipeline(self.config, "Built-in IQ Simulator")
        rng = np.random.default_rng(20260711)
        sample_index = 0
        started = time.monotonic()
        deadline = started
        visible_span = min(self.config.span, self.config.sample_rate)
        offset_1 = 0.17 * visible_span
        offset_2 = -0.28 * visible_span

        try:
            while not self._stop_event.is_set():
                elapsed = time.monotonic() - started
                indices = sample_index + np.arange(self.config.fft_size, dtype=np.float64)
                # A smoothly varying carrier and a periodically changing second
                # carrier make hold and average traces visibly different.
                amplitude_1 = 0.30 + 0.16 * np.sin(2.0 * np.pi * elapsed / 3.0)
                amplitude_2 = 0.16 if int(elapsed * 2.0) % 2 == 0 else 0.045
                tone_1 = amplitude_1 * np.exp(
                    2j * np.pi * offset_1 * indices / self.config.sample_rate
                )
                tone_2 = amplitude_2 * np.exp(
                    2j * np.pi * offset_2 * indices / self.config.sample_rate
                )
                noise = 0.006 * (
                    rng.standard_normal(self.config.fft_size)
                    + 1j * rng.standard_normal(self.config.fft_size)
                )
                samples = (tone_1 + tone_2 + noise).astype(np.complex64)
                frame_callback(pipeline.process(samples))
                sample_index += self.config.fft_size

                deadline += 1.0 / self.frame_rate
                remaining = deadline - time.monotonic()
                if remaining < 0:
                    deadline = time.monotonic()
                    remaining = 0
                self._stop_event.wait(remaining)
        finally:
            if status_callback:
                status_callback("Idle")


def _load_soapy():
    try:
        import SoapySDR
    except (ImportError, OSError) as exc:
        raise AcquisitionError(
            "SoapySDR Python bindings could not be loaded. Start this program from "
            "the Radioconda Prompt and install the packages listed in INSTALL.md."
        ) from exc
    return SoapySDR


def enumerate_devices(device_type: str) -> list[dict[str, str]]:
    soapy = _load_soapy()
    wanted = DRIVER_NAMES.get(device_type.upper())
    if not wanted:
        raise AcquisitionError(f"Unsupported SDR type: {device_type}")
    devices = []
    for entry in soapy.Device.enumerate():
        item = {str(k): str(v) for k, v in dict(entry).items()}
        if item.get("driver", "").lower() in wanted:
            devices.append(item)
    return devices


class SoapyAcquisition:
    def __init__(self, config: AcquisitionConfig):
        self.config = config
        self._stop_event = threading.Event()
        self._device = None
        self._stream = None

    def stop(self):
        self._stop_event.set()

    def _open(self):
        soapy = _load_soapy()
        matches = enumerate_devices(self.config.device_type)
        if not matches:
            drivers = ", ".join(sorted(DRIVER_NAMES[self.config.device_type.upper()]))
            raise AcquisitionError(
                f"No {self.config.device_type} was found by SoapySDR "
                f"(expected driver: {drivers}). Run 'SoapySDRUtil --find' to diagnose."
            )

        self._device = soapy.Device(matches[0])
        direction = soapy.SOAPY_SDR_RX
        channel = self.config.channel
        try:
            self._device.setSampleRate(direction, channel, self.config.sample_rate)
            self._device.setFrequency(direction, channel, self.config.center_frequency)
            try:
                if self._device.hasGainMode(direction, channel):
                    self._device.setGainMode(direction, channel, False)
            except (AttributeError, RuntimeError):
                pass
            requested_gain = self.config.gain
            try:
                gain_range = self._device.getGainRange(direction, channel)
                requested_gain = min(max(requested_gain, gain_range.minimum()), gain_range.maximum())
            except (AttributeError, RuntimeError):
                pass
            self._device.setGain(direction, channel, requested_gain)
            actual_rate = float(self._device.getSampleRate(direction, channel))
            actual_frequency = float(self._device.getFrequency(direction, channel))
            if abs(actual_rate - self.config.sample_rate) / self.config.sample_rate > 0.01:
                raise AcquisitionError(
                    f"Device selected {actual_rate/1e6:.3f} Msps instead of the requested "
                    f"{self.config.sample_rate/1e6:.3f} Msps. Select a supported sample rate."
                )
            self.config = AcquisitionConfig(
                device_type=self.config.device_type,
                center_frequency=actual_frequency,
                sample_rate=actual_rate,
                span=min(self.config.span, actual_rate),
                gain=requested_gain,
                fft_size=self.config.fft_size,
                channel=channel,
            )
            self._stream = self._device.setupStream(direction, soapy.SOAPY_SDR_CF32)
            self._device.activateStream(self._stream)
        except Exception as exc:
            self._close()
            if isinstance(exc, AcquisitionError):
                raise
            raise AcquisitionError(f"Could not configure {self.config.device_type}: {exc}") from exc

        label = matches[0].get("label") or matches[0].get("hardware") or self.config.device_type
        return soapy, DeviceInfo(
            connected=True,
            device_name=label,
            driver=matches[0].get("driver", "Unknown"),
            serial_number=matches[0].get("serial", "Unknown"),
            hardware_key=matches[0].get("hardware", "Unknown"),
            details=matches[0],
        )

    def run(
        self,
        frame_callback: Callable[[object], None],
        status_callback: Callable[[str], None] | None = None,
    ):
        soapy = None
        try:
            soapy, info = self._open()
            if status_callback:
                status_callback(f"Connected: {info.device_name}")
            pipeline = AnalyzerPipeline(self.config, info.device_name)
            block = np.empty(self.config.fft_size, dtype=np.complex64)
            filled = 0
            last_emit = 0.0
            timeout_code = getattr(soapy, "SOAPY_SDR_TIMEOUT", -1)
            overflow_code = getattr(soapy, "SOAPY_SDR_OVERFLOW", -4)
            while not self._stop_event.is_set():
                result = self._device.readStream(
                    self._stream,
                    [block[filled:]],
                    self.config.fft_size - filled,
                    timeoutUs=200_000,
                )
                if result.ret > 0:
                    filled += result.ret
                    if filled == self.config.fft_size:
                        frame = pipeline.process(block.copy())
                        now = time.monotonic()
                        if now - last_emit >= 1.0 / 30.0:
                            frame_callback(frame)
                            last_emit = now
                        filled = 0
                elif result.ret in (timeout_code, overflow_code):
                    continue
                else:
                    error_text = soapy.errToStr(result.ret) if hasattr(soapy, "errToStr") else str(result.ret)
                    raise AcquisitionError(f"SDR stream read failed: {error_text}")
        finally:
            self._close()
            if status_callback:
                status_callback("Idle")

    def _close(self):
        if self._device is not None and self._stream is not None:
            try:
                self._device.deactivateStream(self._stream)
            except Exception:
                pass
            try:
                self._device.closeStream(self._stream)
            except Exception:
                pass
        self._stream = None
        self._device = None

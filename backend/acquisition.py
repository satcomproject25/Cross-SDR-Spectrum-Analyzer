"""Continuous receive-only SDR acquisition through SoapySDR.

HackRF One and Ettus USRP use separate bring-up paths so device-specific
configuration cannot leak from one driver into the other.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from .controller import AnalyzerPipeline
from .calibration import load_device_calibration
from .models import AcquisitionConfig, DeviceInfo


HACKRF_DRIVER = "hackrf"
USRP_DRIVER = "uhd"

# HackRF One hardware limits.
HACKRF_MIN_FREQ = 1e6
HACKRF_MAX_FREQ = 6e9
HACKRF_MIN_RATE = 2e6
HACKRF_MAX_RATE = 20e6

# X300-series motherboard ceiling. A 160 MHz usable span requires a compatible
# wide-band daughterboard and a 10 GigE or PCIe host connection.
USRP_X3X0_MAX_RATE = 200e6
USRP_X3X0_MAX_SPAN = 160e6

# Front-end amp. Keep OFF for signal-generator work: +14 dB into a HackRF that is
# already fed a strong CW tone will compress the ADC and can damage the LNA.
HACKRF_AMP_DB = 0.0
HACKRF_LNA_DB = 24.0        # 0..40 dB, 8 dB steps
HACKRF_VGA_MAX = 62.0       # 0..62 dB, 2 dB steps

# libhackrf's device list is not reentrant. Two acquisition threads calling
# enumerate()/make() concurrently will race hackrf_device_list_open() and both
# fail. Serialize the entire bring-up sequence process-wide.
_OPEN_LOCK = threading.Lock()

# Keep UHD discovery/make calls serialized without changing the proven HackRF
# locking path. The two drivers can therefore be stopped and opened independently.
_USRP_OPEN_LOCK = threading.Lock()

# Set True while bringing up hardware. Makes SoapyHackRF print
#   [INFO]  Opening HackRF One #0 ...
#   [DEBUG] setGain VGA RX, channel 0, gain 20
#   [DEBUG] Start RX
#   [ERROR] hackrf_start_rx() failed -- ...  /  Activate RX Stream Failed.
SOAPY_DEBUG_LOG = True


class AcquisitionError(RuntimeError):
    pass


def create_acquisition(config: AcquisitionConfig):
    device_type = config.device_type.upper()
    if device_type == "SIMULATOR":
        return SyntheticAcquisition(config)
    if device_type == "HACKRF":
        return HackRFAcquisition(config)
    if device_type == "USRP":
        return USRPAcquisition(config)
    raise AcquisitionError(
        f"Unsupported device type '{config.device_type}'. This build supports "
        "SIMULATOR, HACKRF, and USRP only."
    )


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
class SyntheticAcquisition:
    """Nearby QPSK/OFDM-like carriers for testing the complete live pipeline."""

    def __init__(self, config: AcquisitionConfig, frame_rate: float = 30.0):
        self.config = config
        self.frame_rate = frame_rate
        self._stop_event = threading.Event()
        self._reset_min_hold_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def reset_min_hold(self):
        self._reset_min_hold_event.set()

    @staticmethod
    def _digital_carrier_block(
        rng,
        fft_size: int,
        sample_rate: float,
        center_offset: float,
        bandwidth: float,
        target_rms: float,
    ) -> np.ndarray:
        """Synthesize one raised-edge, QPSK-loaded multicarrier symbol."""
        bin_count = max(
            8,
            min(fft_size - 1, int(round(bandwidth * fft_size / sample_rate))),
        )
        center_bin = int(round(center_offset * fft_size / sample_rate))
        relative_bins = np.arange(bin_count) - bin_count // 2
        active_bins = (center_bin + relative_bins) % fft_size

        qpsk_indices = rng.integers(0, 4, size=bin_count)
        qpsk = np.exp(1j * (np.pi / 4.0 + qpsk_indices * np.pi / 2.0))

        # A short raised-cosine transition gives the averaged spectrum the
        # shoulders of a bandwidth-limited digital waveform.
        weights = np.ones(bin_count, dtype=np.float64)
        edge_bins = max(2, bin_count // 12)
        edge = np.sin(np.linspace(0.15, np.pi / 2.0, edge_bins)) ** 2
        weights[:edge_bins] = edge
        weights[-edge_bins:] = edge[::-1]

        spectrum = np.zeros(fft_size, dtype=np.complex128)
        spectrum[active_bins] = qpsk * weights
        samples = np.fft.ifft(spectrum) * fft_size
        measured_rms = float(np.sqrt(np.mean(np.abs(samples) ** 2)))
        return samples * (target_rms / max(measured_rms, 1e-12))

    def run(
        self,
        frame_callback: Callable[[object], None],
        status_callback: Callable[[str], None] | None = None,
    ):
        if status_callback:
            status_callback("Connected: Built-in IQ Simulator")
        pipeline = AnalyzerPipeline(self.config, "Built-in IQ Simulator")
        rng = np.random.default_rng(20260711)
        started = time.monotonic()
        deadline = started
        visible_span = min(self.config.span, self.config.sample_rate)
        primary_offset = -0.045 * visible_span
        secondary_offset = 0.055 * visible_span
        primary_bandwidth = 0.075 * visible_span
        secondary_bandwidth = 0.030 * visible_span

        try:
            while not self._stop_event.is_set():
                if self._reset_min_hold_event.is_set():
                    pipeline.traces.reset_min_hold()
                    self._reset_min_hold_event.clear()
                elapsed = time.monotonic() - started
                primary = self._digital_carrier_block(
                    rng,
                    self.config.fft_size,
                    self.config.sample_rate,
                    primary_offset,
                    primary_bandwidth,
                    0.13 * (1.0 + 0.08 * np.sin(2.0 * np.pi * elapsed / 3.0)),
                )
                secondary = self._digital_carrier_block(
                    rng,
                    self.config.fft_size,
                    self.config.sample_rate,
                    secondary_offset,
                    secondary_bandwidth,
                    0.07 * (1.0 + 0.15 * np.sin(2.0 * np.pi * elapsed / 2.2)),
                )
                noise = 0.0035 * (
                    rng.standard_normal(self.config.fft_size)
                    + 1j * rng.standard_normal(self.config.fft_size)
                )
                samples = primary + secondary + noise
                peak = float(np.max(np.abs(samples)))
                if peak > 0.92:
                    samples *= 0.92 / peak
                samples = samples.astype(np.complex64)
                frame_callback(pipeline.process(samples))

                deadline += 1.0 / self.frame_rate
                remaining = deadline - time.monotonic()
                if remaining < 0:
                    deadline = time.monotonic()
                    remaining = 0
                self._stop_event.wait(remaining)
        finally:
            if status_callback:
                status_callback("Idle")


# ---------------------------------------------------------------------------
# SoapySDR loading / discovery
# ---------------------------------------------------------------------------
def _load_soapy():
    try:
        import SoapySDR
    except (ImportError, OSError) as exc:
        raise AcquisitionError(
            "SoapySDR Python bindings could not be loaded. Launch from the "
            "Radioconda Prompt (see INSTALL.md)."
        ) from exc
    return SoapySDR


def enumerate_hackrf() -> list[dict[str, str]]:
    soapy = _load_soapy()
    devices = []
    for entry in soapy.Device.enumerate(dict(driver=HACKRF_DRIVER)):
        item = {str(k): str(entry[k]) for k in entry.keys()}
        if item.get("driver", "").lower() == HACKRF_DRIVER:
            devices.append(item)
    return devices


def enumerate_usrp() -> list[dict[str, str]]:
    """Discover only Ettus devices exposed by the SoapyUHD driver."""
    soapy = _load_soapy()
    devices = []
    for entry in soapy.Device.enumerate(dict(driver=USRP_DRIVER)):
        item = {str(k): str(entry[k]) for k in entry.keys()}
        if item.get("driver", "").lower() == USRP_DRIVER:
            devices.append(item)
    return devices


# Back-compat shim for backend/main.py and the tests.
def enumerate_devices(device_type: str = "HACKRF") -> list[dict[str, str]]:
    device_type = device_type.upper()
    if device_type == "HACKRF":
        return enumerate_hackrf()
    if device_type == "USRP":
        return enumerate_usrp()
    raise AcquisitionError(f"Unsupported SDR type: {device_type}")


# ---------------------------------------------------------------------------
# HackRF One, receive only
# ---------------------------------------------------------------------------
class HackRFAcquisition:
    def __init__(self, config: AcquisitionConfig):
        self.config = self._validate(config)
        self._stop_event = threading.Event()
        self._soapy = None
        self._device = None
        self._stream = None
        self._reset_min_hold_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def reset_min_hold(self):
        self._reset_min_hold_event.set()

    # -- configuration -----------------------------------------------------
    @staticmethod
    def _validate(config: AcquisitionConfig) -> AcquisitionConfig:
        if not (HACKRF_MIN_FREQ <= config.center_frequency <= HACKRF_MAX_FREQ):
            raise AcquisitionError(
                f"Center frequency {config.center_frequency/1e6:.3f} MHz is outside the "
                f"HackRF One range ({HACKRF_MIN_FREQ/1e6:.0f} MHz - "
                f"{HACKRF_MAX_FREQ/1e9:.0f} GHz)."
            )
        if not (HACKRF_MIN_RATE <= config.sample_rate <= HACKRF_MAX_RATE):
            raise AcquisitionError(
                f"Sample rate {config.sample_rate/1e6:.3f} Msps is outside the HackRF One "
                f"range ({HACKRF_MIN_RATE/1e6:.0f} - {HACKRF_MAX_RATE/1e6:.0f} Msps)."
            )
        return config

    def _apply_gains(self, direction, channel, requested_gain: float) -> float:
        """Set AMP / LNA / VGA explicitly.

        Never use the aggregate Device::setGain(dir, chan, value): the SoapySDR
        base class distributes the value across AMP, LNA and VGA in registry
        order, which silently switches on the 14 dB front-end amp.
        """
        vga = 2.0 * round(max(0.0, min(HACKRF_VGA_MAX, requested_gain)) / 2.0)
        self._device.setGain(direction, channel, "AMP", HACKRF_AMP_DB)
        self._device.setGain(direction, channel, "LNA", HACKRF_LNA_DB)
        self._device.setGain(direction, channel, "VGA", vga)
        return vga

    # -- bring-up ----------------------------------------------------------
    def _open(self):
        with _OPEN_LOCK:
            return self._open_locked()

    def _open_locked(self):
        soapy = _load_soapy()
        self._soapy = soapy
        if SOAPY_DEBUG_LOG:
            try:
                soapy.setLogLevel(soapy.SOAPY_SDR_DEBUG)
            except AttributeError:
                pass

        matches = enumerate_hackrf()
        if not matches:
            raise AcquisitionError(
                "No HackRF One found by SoapySDR. Check the USB cable, then run "
                "'hackrf_info' and 'SoapySDRUtil --find=\"driver=hackrf\"'."
            )
        if len(matches) > 1:
            raise AcquisitionError(
                f"{len(matches)} HackRFs found. This build expects exactly one."
            )

        # Use the KEYWORD form. SoapySDR.py:1833 Device.__new__ only marshals args
        # into a C++ Kwargs map on the `if kwargs:` branch; a positional dict falls
        # through to Device_make(dict), SWIG fails to convert it, the map arrives
        # empty, and Factory.cpp:183 throws "Device::make() no match".
        self._device = soapy.Device(f"driver={HACKRF_DRIVER}")

        direction = soapy.SOAPY_SDR_RX          # receive only; TX is never set up
        channel = 0

        try:
            # SoapyHackRF latches rate / freq / bandwidth / gains into its
            # _rx_stream at setupStream() time, so all of this must precede it.
            self._device.setSampleRate(direction, channel, self.config.sample_rate)
            self._device.setFrequency(direction, channel, self.config.center_frequency)
            try:
                self._device.setBandwidth(direction, channel, self.config.sample_rate)
            except (AttributeError, RuntimeError):
                pass

            applied_gain = self._apply_gains(direction, channel, float(self.config.gain))

            actual_rate = float(self._device.getSampleRate(direction, channel))
            # SoapyHackRF getFrequency() returns its cached tune request, not a
            # hardware PLL measurement. Apply the measured display-axis correction
            # separately so the setpoint and calibration are never confused.
            driver_freq = float(self._device.getFrequency(direction, channel))
            calibration = load_device_calibration(
                "HACKRF", matches[0].get("serial", "")
            )
            axis_offset = float(calibration.get("frequency_axis_offset_hz") or 0.0)
            calibrated_freq = driver_freq + axis_offset
            if abs(actual_rate - self.config.sample_rate) / self.config.sample_rate > 0.01:
                raise AcquisitionError(
                    f"HackRF selected {actual_rate/1e6:.3f} Msps instead of the requested "
                    f"{self.config.sample_rate/1e6:.3f} Msps."
                )

            self.config = AcquisitionConfig(
                device_type="HACKRF",
                center_frequency=calibrated_freq,
                sample_rate=actual_rate,
                span=min(self.config.span, actual_rate),
                gain=applied_gain,
                fft_size=self.config.fft_size,
                channel=channel,
            )

            self._stream = self._device.setupStream(
                direction, soapy.SOAPY_SDR_CF32, [channel]
            )

            # SoapyHackRF::activateStream() reports failure with a RETURN CODE
            # (SOAPY_SDR_STREAM_ERROR = -2), never with a C++ exception. If this is
            # ignored, _current_mode stays HACKRF_TRANSCEIVER_MODE_OFF, the RX LED
            # never lights, and the app streams nothing while reporting "Connected".
            rc = self._device.activateStream(self._stream)
            if rc != 0:
                detail = soapy.errToStr(rc) if hasattr(soapy, "errToStr") else str(rc)
                raise AcquisitionError(
                    f"activateStream failed ({rc}: {detail}). The HackRF opened but never "
                    "entered RX mode (hackrf_start_rx did not latch; the RX LED stays "
                    "off). Close anything else holding the board, unplug/replug it, and "
                    "try a lower sample rate."
                )

        except Exception as exc:
            self._close()
            if isinstance(exc, AcquisitionError):
                raise
            raise AcquisitionError(f"Could not configure the HackRF One: {exc}") from exc

        return soapy, DeviceInfo(
            connected=True,
            device_name=matches[0].get("label", "HackRF One"),
            driver=HACKRF_DRIVER,
            serial_number=matches[0].get("serial", "Unknown"),
            hardware_key=matches[0].get("device", "HackRF One"),
            details={
                **matches[0],
                "driver_frequency_hz": str(driver_freq),
                "frequency_axis_offset_hz": str(axis_offset),
                "display_center_frequency_hz": str(calibrated_freq),
            },
        )

    # -- streaming ---------------------------------------------------------
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
            last_sample = time.monotonic()

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
                    last_sample = time.monotonic()
                    filled += result.ret
                    if filled == self.config.fft_size:
                        now = time.monotonic()
                        if now - last_emit >= 1.0 / 30.0:
                            if self._reset_min_hold_event.is_set():
                                pipeline.traces.reset_min_hold()
                                self._reset_min_hold_event.clear()
                            frame = pipeline.process(block.copy())
                            frame_callback(frame)
                            last_emit = now
                        filled = 0

                # ret == 0 is a legal short read. Overflow means we fell behind:
                # the samples are gone but the stream is still alive.
                elif result.ret == 0 or result.ret in (timeout_code, overflow_code):
                    if time.monotonic() - last_sample > 5.0:
                        raise AcquisitionError(
                            "HackRF is open but has delivered no IQ for 5 s. The RX path "
                            "is not running (check the RX LED). Confirm with: "
                            "hackrf_transfer -r NUL -f "
                            f"{int(self.config.center_frequency)} -s "
                            f"{int(self.config.sample_rate)} -n 20000000"
                        )
                    continue

                else:
                    detail = (
                        soapy.errToStr(result.ret)
                        if hasattr(soapy, "errToStr")
                        else str(result.ret)
                    )
                    raise AcquisitionError(f"HackRF stream read failed: {detail}")

        finally:
            self._close()
            if status_callback:
                status_callback("Idle")

    # -- teardown ----------------------------------------------------------
    def _close(self):
        """Fully release the device.

        Device::make() is refcount-cached in the SoapySDR factory registry and the
        SWIG proxy has no destructor bound to unmake(). Dropping the Python
        reference alone leaves the HackRF USB handle open, so the next open()
        receives the same half-torn-down C++ instance and hackrf_start_rx() fails.
        unmake() is mandatory.
        """
        device, stream, soapy = self._device, self._stream, self._soapy

        if device is not None and stream is not None:
            try:
                device.deactivateStream(stream)   # hackrf_stop_rx -> RX LED off
            except Exception:
                pass
            try:
                device.closeStream(stream)
            except Exception:
                pass

        if device is not None:
            try:
                if soapy is None:
                    soapy = _load_soapy()
                soapy.Device.unmake(device)       # hackrf_close
            except Exception:
                pass

        self._stream = None
        self._device = None
        self._soapy = None


# ---------------------------------------------------------------------------
# Ettus USRP through SoapyUHD, receive only
# ---------------------------------------------------------------------------
class USRPAcquisition:
    """Configure and continuously stream one USRP without touching HackRF state."""

    def __init__(self, config: AcquisitionConfig):
        self.config = self._validate(config)
        self._stop_event = threading.Event()
        self._reset_min_hold_event = threading.Event()
        self._soapy = None
        self._device = None
        self._stream = None

    @staticmethod
    def _validate(config: AcquisitionConfig) -> AcquisitionConfig:
        if config.sample_rate <= 0 or config.sample_rate > USRP_X3X0_MAX_RATE:
            raise AcquisitionError(
                f"USRP sample rate must be above 0 and no more than "
                f"{USRP_X3X0_MAX_RATE/1e6:.0f} MS/s for the X300-series profile."
            )
        if config.span <= 0 or config.span > USRP_X3X0_MAX_SPAN:
            raise AcquisitionError(
                f"USRP span must be above 0 and no more than "
                f"{USRP_X3X0_MAX_SPAN/1e6:.0f} MHz for the X300-series profile."
            )
        if config.span > config.sample_rate:
            raise AcquisitionError("USRP span cannot exceed its sample rate.")
        return config

    def stop(self):
        self._stop_event.set()

    def reset_min_hold(self):
        self._reset_min_hold_event.set()

    @staticmethod
    def _selector(match: dict[str, str]) -> str:
        """Build a stable selector for the single device found during discovery."""
        parts = [f"driver={USRP_DRIVER}"]
        for key in ("serial", "addr"):
            value = match.get(key)
            if value:
                parts.append(f"{key}={value}")
                break
        return ",".join(parts)

    def _apply_gain(self, direction, channel, requested_gain: float) -> float:
        gain = float(requested_gain)
        try:
            gain_range = self._device.getGainRange(direction, channel)
            gain = max(float(gain_range.minimum()), min(float(gain_range.maximum()), gain))
        except (AttributeError, RuntimeError, TypeError):
            pass

        try:
            if self._device.hasGainMode(direction, channel):
                self._device.setGainMode(direction, channel, False)
        except (AttributeError, RuntimeError):
            pass

        self._device.setGain(direction, channel, gain)
        return gain

    def _open(self):
        with _USRP_OPEN_LOCK:
            return self._open_locked()

    def _open_locked(self):
        soapy = _load_soapy()
        self._soapy = soapy

        matches = enumerate_usrp()
        if not matches:
            raise AcquisitionError(
                "No Ettus USRP found by SoapyUHD. Check power/network or USB, then "
                "run 'uhd_find_devices' and 'SoapySDRUtil --find=\"driver=uhd\"'."
            )
        if len(matches) > 1:
            raise AcquisitionError(
                f"{len(matches)} USRPs found. Connect exactly one before starting this build."
            )

        match = matches[0]
        self._device = soapy.Device(self._selector(match))
        direction = soapy.SOAPY_SDR_RX
        channel = int(self.config.channel)

        try:
            self._device.setSampleRate(direction, channel, self.config.sample_rate)
            self._device.setFrequency(direction, channel, self.config.center_frequency)
            try:
                self._device.setBandwidth(
                    direction, channel, min(self.config.span, self.config.sample_rate)
                )
            except (AttributeError, RuntimeError):
                pass

            applied_gain = self._apply_gain(direction, channel, self.config.gain)
            actual_rate = float(self._device.getSampleRate(direction, channel))
            actual_freq = float(self._device.getFrequency(direction, channel))
            if actual_rate <= 0 or (
                abs(actual_rate - self.config.sample_rate) / self.config.sample_rate > 0.01
            ):
                raise AcquisitionError(
                    f"USRP selected {actual_rate/1e6:.3f} Msps instead of the requested "
                    f"{self.config.sample_rate/1e6:.3f} Msps. Choose a supported rate."
                )

            self.config = AcquisitionConfig(
                device_type="USRP",
                center_frequency=actual_freq,
                sample_rate=actual_rate,
                span=min(self.config.span, actual_rate),
                gain=applied_gain,
                fft_size=self.config.fft_size,
                channel=channel,
            )
            self._stream = self._device.setupStream(
                direction, soapy.SOAPY_SDR_CF32, [channel]
            )
            rc = self._device.activateStream(self._stream)
            if rc not in (None, 0):
                detail = soapy.errToStr(rc) if hasattr(soapy, "errToStr") else str(rc)
                raise AcquisitionError(f"USRP activateStream failed ({rc}: {detail}).")
        except Exception as exc:
            self._close()
            if isinstance(exc, AcquisitionError):
                raise
            raise AcquisitionError(f"Could not configure the Ettus USRP: {exc}") from exc

        return soapy, DeviceInfo(
            connected=True,
            device_name=match.get("label", match.get("name", "Ettus USRP")),
            driver=USRP_DRIVER,
            serial_number=match.get("serial", "Unknown"),
            hardware_key=match.get("type", match.get("hardware", "USRP")),
            details=match,
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
            last_sample = time.monotonic()
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
                    last_sample = time.monotonic()
                    filled += result.ret
                    if filled == self.config.fft_size:
                        now = time.monotonic()
                        if now - last_emit >= 1.0 / 30.0:
                            if self._reset_min_hold_event.is_set():
                                pipeline.traces.reset_min_hold()
                                self._reset_min_hold_event.clear()
                            frame_callback(pipeline.process(block.copy()))
                            last_emit = now
                        filled = 0
                elif result.ret == 0 or result.ret in (timeout_code, overflow_code):
                    if time.monotonic() - last_sample > 5.0:
                        raise AcquisitionError(
                            "USRP is configured but has delivered no IQ samples for 5 s. "
                            "Check its connection and RX channel with 'uhd_usrp_probe'."
                        )
                else:
                    detail = (
                        soapy.errToStr(result.ret)
                        if hasattr(soapy, "errToStr")
                        else str(result.ret)
                    )
                    raise AcquisitionError(f"USRP stream read failed: {detail}")
        finally:
            self._close()
            if status_callback:
                status_callback("Idle")

    def _close(self):
        device, stream, soapy = self._device, self._stream, self._soapy
        if device is not None and stream is not None:
            try:
                device.deactivateStream(stream)
            except Exception:
                pass
            try:
                device.closeStream(stream)
            except Exception:
                pass
        if device is not None:
            try:
                if soapy is None:
                    soapy = _load_soapy()
                soapy.Device.unmake(device)
            except Exception:
                pass
        self._stream = None
        self._device = None
        self._soapy = None


# Legacy alias so existing imports of SoapyAcquisition keep working.
SoapyAcquisition = HackRFAcquisition

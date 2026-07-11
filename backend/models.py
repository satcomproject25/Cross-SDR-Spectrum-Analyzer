"""Data contracts shared by the acquisition, DSP, and GUI layers."""

from dataclasses import dataclass, field
import numpy as np


@dataclass
class DeviceInfo:
    connected: bool = False
    device_name: str = "Unknown"
    driver: str = "Unknown"
    serial_number: str = "Unknown"
    hardware_key: str = "Unknown"
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AcquisitionConfig:
    device_type: str
    center_frequency: float
    sample_rate: float
    span: float
    gain: float
    fft_size: int = 4096
    channel: int = 0


@dataclass
class IQFrame:
    samples: np.ndarray
    frame_number: int
    sample_rate: float
    center_frequency: float


@dataclass
class SpectrumData:
    frequency: np.ndarray
    amplitude: np.ndarray
    center_frequency: float
    span: float
    sample_rate: float
    fft_size: int
    rbw: float


@dataclass
class TraceData:
    frequency: np.ndarray
    live: np.ndarray
    max_hold: np.ndarray
    min_hold: np.ndarray
    average: np.ndarray
    frame_count: int


@dataclass
class Peak:
    id: int
    frequency: float
    amplitude: float
    bin_index: int


@dataclass
class MeasurementData:
    peak_frequency: float
    peak_amplitude: float
    noise_floor: float
    occupied_bandwidth: float
    channel_power: float
    carrier_bandwidth: float


@dataclass
class SpectrumFrame:
    """Flat frame contract consumed directly by the frontend."""

    frequency: np.ndarray
    amplitude: np.ndarray
    max_hold: np.ndarray
    min_hold: np.ndarray
    average: np.ndarray
    peaks: list[Peak]
    bandwidth: float
    timestamp: float
    noise_floor: float
    channel_power: float
    carrier_bandwidth: float
    center_frequency: float
    sample_rate: float
    span: float
    fft_size: int
    rbw: float
    frame_count: int
    device_name: str = ""


# Legacy file-capture models are retained for old recordings and scripts.
@dataclass
class CaptureConfig:
    center_frequency: int
    sample_rate: int
    sample_count: int
    lna_gain: int = 16
    vga_gain: int = 20
    amp_enable: bool = False
    filename: str = "capture.iq"


@dataclass
class IQBuffer:
    samples: np.ndarray
    sample_rate: int
    center_frequency: int


@dataclass
class Marker:
    id: int
    frequency: float
    amplitude: float
    bin_index: int
    enabled: bool = True


@dataclass
class PeakTable:
    peaks: list[Peak]

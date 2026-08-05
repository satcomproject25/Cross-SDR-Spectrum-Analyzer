"""Compact binary protocol for browser spectrum frames."""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np


TRACE_NAMES = ("amplitude", "max_hold", "min_hold", "average")
HEADER_LENGTH = struct.Struct("<I")


def _display_trace(frame, name: str):
    calibrated = getattr(frame, f"{name}_dbm", None)
    if calibrated is not None:
        return calibrated
    raw = getattr(frame, f"{name}_dbfs", None)
    if raw is not None:
        return raw
    return getattr(frame, name)


def _display_peaks(frame):
    peaks = getattr(frame, "peaks_dbm", None)
    if not peaks:
        peaks = getattr(frame, "peaks", ())
    return [
        {
            "id": int(peak.id),
            "frequency": float(peak.frequency),
            "amplitude": float(peak.amplitude),
            "bin": int(peak.bin_index),
        }
        for peak in peaks
    ]


def _carrier_value(carrier, *names, offset_db: float = 0.0) -> float | None:
    """First present attribute, preferring calibrated dBm over raw dBFS.

    ``offset_db`` is added only when the matched attribute is a raw level, so a
    calibrated frame never renders a carrier table that mixes dBm rows with
    dBFS rows. Pass ``offset_db=0.0`` for frequencies, bandwidths, and ratios.
    """
    for name in names:
        for candidate, is_raw in ((f"{name}_dbm", False), (f"{name}_dbfs", True), (name, True)):
            value = getattr(carrier, candidate, None)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number != number:  # reject NaN
                continue
            return number + offset_db if is_raw else number
    return None


def _pack_carriers(frame, frequency: np.ndarray) -> list[dict[str, Any]]:
    """Serialize detected/measured carriers.

    Bin indices always come from ``carrier_detection``. Physical quantities are
    taken from ``carrier_measure`` when the measurement stage has run, and are
    otherwise reconstructed from the bin geometry so an uninstrumented
    ``CarrierRegion`` still renders a usable table row.
    """
    bin_count = int(frequency.size)
    step = float(frequency[1] - frequency[0]) if bin_count > 1 else 0.0
    packed: list[dict[str, Any]] = []

    raw_offset = 0.0
    if getattr(frame, "power_calibrated", False):
        try:
            raw_offset = float(getattr(frame, "power_offset_db", 0.0) or 0.0)
        except (TypeError, ValueError):
            raw_offset = 0.0

    for index, carrier in enumerate(getattr(frame, "carriers", None) or ()):
        left = int(getattr(carrier, "left_bin", 0))
        right = int(getattr(carrier, "right_bin", left))
        center_bin = int(getattr(carrier, "center_bin", (left + right) // 2))
        peak_bin = int(getattr(carrier, "peak_bin", center_bin))

        def bin_frequency(bin_index: int) -> float:
            clamped = max(0, min(bin_count - 1, bin_index))
            return float(frequency[clamped]) if bin_count else 0.0

        center_frequency = _carrier_value(carrier, "center_frequency", "frequency")
        if center_frequency is None:
            center_frequency = bin_frequency(center_bin)

        occupied = _carrier_value(
            carrier, "occupied_bandwidth", "bandwidth", "obw"
        )
        if occupied is None:
            occupied = abs(step) * max(0, right - left)

        packed.append(
            {
                "id": int(getattr(carrier, "id", index + 1) or index + 1),
                "left": left,
                "right": right,
                "center": center_bin,
                "peak": peak_bin,
                "center_frequency": center_frequency,
                "occupied_bandwidth": float(occupied),
                "power": _carrier_value(
                    carrier, "band_power", "channel_power", "power",
                    offset_db=raw_offset,
                ),
                "peak_power": _carrier_value(
                    carrier, "peak_power", offset_db=raw_offset
                ),
                "noise_floor": _carrier_value(
                    carrier, "noise_floor", offset_db=raw_offset
                ),
                "snr": _carrier_value(carrier, "snr", "snr_db"),
                "age": int(getattr(carrier, "age", 0) or 0),
                "confidence": float(getattr(carrier, "confidence", 1.0)),
            }
        )
    return packed


def _scalar(frame, name: str) -> float:
    calibrated = getattr(frame, f"{name}_dbm", None)
    if calibrated is not None:
        return float(calibrated)
    raw = getattr(frame, f"{name}_dbfs", None)
    if raw is not None:
        return float(raw)
    return float(getattr(frame, name))


def pack_spectrum_frame(frame) -> bytes:
    """Encode JSON metadata followed by four contiguous Float32 traces."""
    frequency = np.asarray(frame.frequency, dtype=np.float64)
    arrays = [
        np.ascontiguousarray(_display_trace(frame, name), dtype="<f4")
        for name in TRACE_NAMES
    ]
    bin_count = int(frequency.size)
    if any(array.size != bin_count for array in arrays):
        raise ValueError("All spectrum traces must have the same number of bins")

    carriers = _pack_carriers(frame, frequency)
    header: dict[str, Any] = {
        "type": "frame",
        "version": 1,
        "bins": bin_count,
        "traces": TRACE_NAMES,
        "frequency_start": float(frequency[0]) if bin_count else 0.0,
        "frequency_step": (
            float(frequency[1] - frequency[0]) if bin_count > 1 else 0.0
        ),
        "unit": str(
            getattr(frame, "amplitude_unit", getattr(frame, "unit", "dBFS"))
        ),
        "center_frequency": float(frame.center_frequency),
        "sample_rate": float(frame.sample_rate),
        "span": float(frame.span),
        "fft_size": int(frame.fft_size),
        "rbw": float(frame.rbw),
        "frame_count": int(frame.frame_count),
        "timestamp": float(frame.timestamp),
        "device_name": str(getattr(frame, "device_name", "")),
        "power_calibrated": bool(getattr(frame, "power_calibrated", False)),
        "power_offset_db": getattr(frame, "power_offset_db", None),
        "bandwidth": float(frame.bandwidth),
        "noise_floor": _scalar(frame, "noise_floor"),
        "channel_power": _scalar(frame, "channel_power"),
        "peaks": _display_peaks(frame),
        "carriers": carriers,
    }
    header_bytes = json.dumps(
        header, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    payload = b"".join(array.tobytes(order="C") for array in arrays)
    return HEADER_LENGTH.pack(len(header_bytes)) + header_bytes + payload


def unpack_spectrum_frame(packet: bytes) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Decode a packet for tests and non-browser clients."""
    if len(packet) < HEADER_LENGTH.size:
        raise ValueError("Spectrum packet is truncated")
    (header_length,) = HEADER_LENGTH.unpack_from(packet)
    header_end = HEADER_LENGTH.size + header_length
    if header_end > len(packet):
        raise ValueError("Spectrum packet header is truncated")
    header = json.loads(packet[HEADER_LENGTH.size:header_end].decode("utf-8"))
    bins = int(header["bins"])
    traces: dict[str, np.ndarray] = {}
    offset = header_end
    byte_count = bins * np.dtype("<f4").itemsize
    for name in header["traces"]:
        end = offset + byte_count
        if end > len(packet):
            raise ValueError("Spectrum packet trace data is truncated")
        traces[name] = np.frombuffer(packet[offset:end], dtype="<f4").copy()
        offset = end
    if offset != len(packet):
        raise ValueError("Spectrum packet contains unexpected trailing data")
    return header, traces
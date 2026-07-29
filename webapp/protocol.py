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

    carriers = [
        {
            "left": int(carrier.left_bin),
            "right": int(carrier.right_bin),
            "center": int(carrier.center_bin),
            "peak": int(carrier.peak_bin),
            "confidence": float(getattr(carrier, "confidence", 1.0)),
        }
        for carrier in (getattr(frame, "carriers", None) or ())
    ]
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

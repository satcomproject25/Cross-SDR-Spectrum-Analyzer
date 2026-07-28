"""Load optional, device-specific measurement calibration values."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "calibration.json"


def load_device_calibration(device_type: str, serial: str = "") -> dict[str, Any]:
    """Return wildcard calibration merged with a serial-specific override."""
    path = Path(os.environ.get("FREQANALYZER_CALIBRATION", DEFAULT_PATH))
    result: dict[str, Any] = {
        "frequency_axis_offset_hz": 0.0,
        "power_offset_db": None,
    }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        device = document.get("devices", {}).get(device_type.upper(), {})
        result.update(device.get("default", {}))
        if serial:
            result.update(device.get("serials", {}).get(serial, {}))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, AttributeError):
        return result
    return result


def calibrated_power_offset(calibration: dict[str, Any]) -> float | None:
    """Return a finite dBFS-to-dBm offset, or ``None`` when uncalibrated."""
    value = calibration.get("power_offset_db")
    if value is None or isinstance(value, bool):
        return None
    try:
        offset = float(value)
    except (TypeError, ValueError):
        return None
    return offset if math.isfinite(offset) else None

# IF OFFSET DOES NOT SCALE LINEARLY, USE THIS
# REMOVE IF IT SCALES LINEARLY
def interpolated_offset_hz(freq_hz: float, table: list[dict]) -> float:
    """Linearly interpolate frequency offset from a sorted calibration table."""
    if not table:
        return 0.0
    if freq_hz <= table[0]["freq_hz"]:
        return table[0]["offset_hz"]
    if freq_hz >= table[-1]["freq_hz"]:
        return table[-1]["offset_hz"]
    for i in range(len(table) - 1):
        lo, hi = table[i], table[i + 1]
        if lo["freq_hz"] <= freq_hz <= hi["freq_hz"]:
            frac = (freq_hz - lo["freq_hz"]) / (hi["freq_hz"] - lo["freq_hz"])
            return lo["offset_hz"] + frac * (hi["offset_hz"] - lo["offset_hz"])
    return 0.0

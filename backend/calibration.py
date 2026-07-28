"""Device frequency/power calibration loading.

Schema (per device serial, falling back to the device 'default'):
    frequency_fixed_error_hz : float   constant offset, Hz
    frequency_ppm_error      : float   proportional error, parts per million
    power_offset_db          : float | None
    power_base_offset_db     : float | None            single-constant power cal
    power_base_offset_table  : list | None             per-frequency power cal
    power_vga_table          : list | None             per-VGA power cal
    power_cal_lna_db         : float | None            LNA the cal was taken at
    power_cal_amp_db         : float | None            AMP the cal was taken at
    power_cal_attenuator_db  : float | None            input pad (already stripped)
    power_cal_vga_min_db     : float | None            calibrated VGA range floor
    power_cal_vga_max_db     : float | None            calibrated VGA range ceiling

Frequency correction applied downstream (see acquisition.py):
    frequency_error_hz = fixed + driver_freq * ppm * 1e-6
    calibrated_freq    = driver_freq - frequency_error_hz

Sign convention (from the calibration procedure doc):
    offset_hz = observed_frequency_hz - reference_frequency_hz
    A POSITIVE error means the project displays too HIGH, so we SUBTRACT.

Power correction (see power_calibration.py):
    dbm = dbfs + power_offset_db,  where power_offset_db is resolved from the
    table(s) above for the live VGA and centre frequency.
"""

from __future__ import annotations

import json
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
        if not isinstance(device, dict):
            return result

        default_calibration = device.get("default", {})
        if isinstance(default_calibration, dict):
            result.update(default_calibration)

        serials = device.get("serials", {})
        if serial and isinstance(serials, dict):
            serial_calibration = serials.get(str(serial), {})
            if isinstance(serial_calibration, dict):
                result.update(serial_calibration)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, AttributeError):
        return result

    return result

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

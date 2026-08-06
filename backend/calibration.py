"""Load and apply device-specific measurement calibration.

Schema (calibration.json)
-------------------------
devices.<TYPE>.default / devices.<TYPE>.serials.<SERIAL> may contain:

    frequency_axis_offset_hz : float   fixed correction added to the tuned freq
    ppm_offset               : float   oscillator error, Hz per MHz of RF
    frequency_offset_table   : [{freq_hz, offset_hz}]   non-linear residual path
    power_base_table         : [{freq_hz, base_db}]     gain-normalised
    power_gain_table         : [{gain_db, delta_db}]    per-gain deviation
    power_reference_gain_db  : float   gain at which the base table was taken
    external_attenuation_db  : float   pad fitted during NORMAL operation
    power_offset_db          : float | null   legacy single-point fallback
    metadata                 : {...}   provenance, uncertainty, timestamp

Sign conventions
----------------
    displayed_hz = driver_hz + frequency_correction_hz(driver_hz, cal)
    dbm          = dbfs + power_offset_db(freq_hz, gain_db, cal)

Both are additive corrections. Nothing here mutates state; the pipeline holds
one PowerCalibration instance and asks it for a scalar per frame.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "calibration.json"

_EMPTY: dict[str, Any] = {
    "frequency_axis_offset_hz": 0.0,
    "ppm_offset": 0.0,
    "frequency_offset_table": [],
    "power_base_table": [],
    "power_gain_table": [],
    "power_reference_gain_db": 0.0,
    "external_attenuation_db": 0.0,
    "power_offset_db": None,
    "metadata": {},
}


def calibration_path() -> Path:
    """Resolve the active calibration file, honouring the env override."""
    return Path(os.environ.get("FREQANALYZER_CALIBRATION", DEFAULT_PATH))


def load_document() -> dict:
    """Return the whole calibration document, or an empty skeleton."""
    try:
        return json.loads(calibration_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"devices": {}}


def load_device_calibration(device_type: str, serial: str = "") -> dict[str, Any]:
    """Wildcard calibration merged with a serial-specific override.

    Kept name-compatible with the previous implementation: existing callers that
    read only ``frequency_axis_offset_hz`` / ``power_offset_db`` keep working.
    """
    result = json.loads(json.dumps(_EMPTY))  # deep copy of mutable defaults
    try:
        device = load_document().get("devices", {}).get(device_type.upper(), {})
        result.update(device.get("default", {}) or {})
        if serial:
            result.update((device.get("serials", {}) or {}).get(serial, {}) or {})
    except (TypeError, AttributeError):
        return result
    return result


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------
def _interp(x: float, table: list[dict], xkey: str, ykey: str) -> float:
    """Linear interpolation with flat extrapolation past both ends.

    Flat rather than linear extrapolation is deliberate: an SDR front end is
    wildly non-linear outside the measured span (see the 2.17 GHz and 2.74 GHz
    band edges), and projecting a slope past the last point invents dB that were
    never measured.
    """
    pts = sorted(
        (
            (float(p[xkey]), float(p[ykey]))
            for p in table
            if p.get(xkey) is not None and p.get(ykey) is not None
        ),
        key=lambda p: p[0],
    )
    if not pts:
        return 0.0
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def interpolated_offset_hz(freq_hz: float, table: list[dict]) -> float:
    """Backward-compatible helper retained for existing call sites."""
    return _interp(freq_hz, table, "freq_hz", "offset_hz")


def frequency_correction_hz(freq_hz: float, cal: dict) -> float:
    """Total additive frequency correction in hertz.

    Combines the fixed axis offset, the oscillator ppm term, and any measured
    non-linear residual. A calibration that only ever set the fixed term is
    unchanged, because ppm and the table both default to zero/empty.
    """
    fixed = float(cal.get("frequency_axis_offset_hz") or 0.0)
    ppm = float(cal.get("ppm_offset") or 0.0)
    table = cal.get("frequency_offset_table") or []
    return fixed - ppm * (freq_hz / 1.0e6) + _interp(freq_hz, table, "freq_hz", "offset_hz")


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------
@dataclass
class PowerCalibration:
    """Frequency- and gain-dependent dBFS -> dBm conversion.

    ``valid`` is False when no table and no legacy scalar exist, and the caller
    must then keep displaying dBFS. Silently showing an uncalibrated number in
    dBm is the one failure mode this class exists to prevent.
    """

    base_table: list[dict]
    gain_table: list[dict]
    reference_gain_db: float = 0.0
    external_attenuation_db: float = 0.0
    legacy_offset_db: float | None = None
    metadata: dict = None

    @classmethod
    def from_calibration(cls, cal: dict) -> "PowerCalibration":
        return cls(
            base_table=list(cal.get("power_base_table") or []),
            gain_table=list(cal.get("power_gain_table") or []),
            reference_gain_db=float(cal.get("power_reference_gain_db") or 0.0),
            external_attenuation_db=float(cal.get("external_attenuation_db") or 0.0),
            legacy_offset_db=cal.get("power_offset_db"),
            metadata=dict(cal.get("metadata") or {}),
        )

    @classmethod
    def for_device(cls, device_type: str, serial: str = "") -> "PowerCalibration":
        return cls.from_calibration(load_device_calibration(device_type, serial))

    @property
    def valid(self) -> bool:
        return bool(self.base_table) or self.legacy_offset_db is not None

    @property
    def frequency_range_hz(self) -> tuple[float, float] | None:
        if not self.base_table:
            return None
        freqs = [float(p["freq_hz"]) for p in self.base_table]
        return min(freqs), max(freqs)

    def in_range(self, freq_hz: float) -> bool:
        """True when freq is inside the measured span (not extrapolated)."""
        span = self.frequency_range_hz
        return span is not None and span[0] <= freq_hz <= span[1]

    def offset_db(self, freq_hz: float, gain_db: float) -> float:
        """Additive dB to convert dBFS to dBm at this frequency and gain."""
        if not self.base_table:
            return float(self.legacy_offset_db or 0.0)
        base = _interp(freq_hz, self.base_table, "freq_hz", "base_db")
        delta = _interp(gain_db, self.gain_table, "gain_db", "delta_db")
        return base + delta - float(gain_db) + self.external_attenuation_db

    def to_dbm(self, dbfs, freq_hz: float, gain_db: float):
        """Scalar or NumPy array conversion."""
        return dbfs + self.offset_db(freq_hz, gain_db)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def save_device_calibration(
    device_type: str,
    serial: str,
    values: dict,
    path: Path | None = None,
) -> Path:
    """Merge ``values`` into the calibration document and write it atomically.

    A timestamped ``.bak`` is written first. The previous file is never lost to
    a partial write: the new document goes to a temp file in the same directory
    and is then renamed, which is atomic on both POSIX and NTFS.
    """
    from datetime import datetime

    target = Path(path or calibration_path())
    document = load_document()
    document.setdefault("devices", {})
    device = document["devices"].setdefault(device_type.upper(), {})
    device.setdefault("default", {})
    device.setdefault("serials", {})

    if serial and serial.lower() not in ("", "unknown", "your_serial_here"):
        bucket = device["serials"].setdefault(serial, {})
    else:
        bucket = device["default"]
    bucket.update(values)

    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = target.with_suffix(f".{stamp}.bak")
        try:
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass

    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(document, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target
"""dBFS -> dBm power calibration.

Measured relationship (see HackRF_Power_Calibration.xlsx):

    offset_db      = siggen_dbm - measured_dbfs        # per measurement row
    norm_offset_db = offset_db + vga_db                # referred back to VGA = 0

If the VGA is linear, norm_offset_db is a CONSTANT across every VGA setting and
(usually) across frequency too. That constant is `power_base_offset_db`, and the
applied correction collapses to:

    power_offset_db = power_base_offset_db - vga_db
    dbm             = dbfs + power_offset_db

Three schemas are supported, in increasing order of complexity. Use the simplest
one your spreadsheet verdicts allow:

  1. constant           "power_base_offset_db": -40.0
  2. per-frequency      "power_base_offset_table": [{"freq_hz":..., "base_offset_db":...}]
  3. per-VGA override   "power_vga_table": [{"vga_db":..., "offset_db":...}]

Schema 3 wins when present (it is a direct lookup of offset_db and already
includes the VGA term, so the -vga_db subtraction is NOT applied on top).
"""

from __future__ import annotations

from typing import Any


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation with endpoint clamping (never extrapolates)."""
    if not points:
        return 0.0
    pts = sorted(points, key=lambda t: t[0])
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xa <= x <= xb:
            if xb == xa:
                return ya
            return ya + (x - xa) / (xb - xa) * (yb - ya)
    return pts[-1][1]


def _as_points(raw: Any, xkey: str, ykey: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and xkey in item and ykey in item:
                try:
                    out.append((float(item[xkey]), float(item[ykey])))
                except (TypeError, ValueError):
                    continue
    return out


def resolve_power_offset_db(
    calibration: dict[str, Any],
    vga_db: float,
    freq_hz: float = 0.0,
) -> float | None:
    """Return power_offset_db to ADD to a dBFS reading to get dBm.

    Returns None when the device has no power calibration at all, so callers can
    keep displaying dBFS rather than silently reporting a wrong absolute power.
    """
    if not isinstance(calibration, dict):
        return None

    # VGA-range guard: the calibration was only characterised over a window of
    # VGA settings. Outside it (e.g. VGA < 20, where a weak tone sinks into the
    # noise floor and the offset was never measured) return None so the caller
    # falls back to honest dBFS instead of reporting a fabricated dBm.
    vga_min = calibration.get("power_cal_vga_min_db")
    vga_max = calibration.get("power_cal_vga_max_db")
    if vga_min is not None and float(vga_db) < float(vga_min):
        return None
    if vga_max is not None and float(vga_db) > float(vga_max):
        return None

    # (3) direct per-VGA lookup: already includes the VGA term.
    vga_pts = _as_points(calibration.get("power_vga_table"), "vga_db", "offset_db")
    if vga_pts:
        return _interp(float(vga_db), vga_pts)

    # (2) frequency-dependent base offset.
    freq_pts = _as_points(
        calibration.get("power_base_offset_table"), "freq_hz", "base_offset_db"
    )
    if freq_pts:
        base = _interp(float(freq_hz), freq_pts)
        return base - float(vga_db)

    # (1) single constant.
    base_raw = calibration.get("power_base_offset_db")
    if base_raw is None:
        # Back-compat: a plain pre-solved constant, VGA already folded in.
        legacy = calibration.get("power_offset_db")
        return None if legacy is None else float(legacy)
    return float(base_raw) - float(vga_db)


def dbfs_to_dbm(dbfs, power_offset_db: float | None):
    """Convert dBFS to dBm. Returns the input unchanged when uncalibrated.

    Works on scalars and on NumPy arrays (whole traces) alike.
    """
    if power_offset_db is None:
        return dbfs
    return dbfs + power_offset_db


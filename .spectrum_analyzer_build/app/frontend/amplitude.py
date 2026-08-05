"""Select calibrated amplitude fields from spectrum frames."""

from __future__ import annotations


TRACE_FIELDS = {
    "amplitude": ("amplitude_dbm", "amplitude_dbfs", "amplitude"),
    "max_hold": ("max_hold_dbm", "max_hold_dbfs", "max_hold"),
    "min_hold": ("min_hold_dbm", "min_hold_dbfs", "min_hold"),
    "average": ("average_dbm", "average_dbfs", "average"),
}


def amplitude_unit(frame) -> str:
    """Return the unit that is valid for the frame's display values."""
    if getattr(frame, "amplitude_dbm", None) is not None:
        return "dBm"
    return getattr(frame, "amplitude_unit", "dBFS")


def trace_amplitude(frame, trace_name: str = "amplitude"):
    """Return calibrated dBm when present, otherwise the raw dBFS trace."""
    try:
        candidates = TRACE_FIELDS[trace_name]
    except KeyError as exc:
        raise ValueError(f"Unknown amplitude trace: {trace_name}") from exc
    for field_name in candidates:
        value = getattr(frame, field_name, None)
        if value is not None:
            return value
    raise AttributeError(f"Frame has no values for {trace_name}")


def scalar_amplitude(frame, name: str) -> float:
    """Return a calibrated scalar measurement with a dBFS compatibility fallback."""
    calibrated = getattr(frame, f"{name}_dbm", None)
    if calibrated is not None:
        return float(calibrated)
    raw = getattr(frame, f"{name}_dbfs", None)
    if raw is not None:
        return float(raw)
    return float(getattr(frame, name))

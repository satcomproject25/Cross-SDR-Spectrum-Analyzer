"""Amplitude unit selection: user intent versus what the numbers actually are.

The unit is NOT a property of the frame. `backend/controller.py` puts raw dBFS
traces on every SpectrumFrame together with a scalar `power_offset_db` and the
flags `power_calibrated` / `power_in_cal_range`. Which of the two the operator
sees is a CHOICE, held here.

Invariant enforced in this module and nowhere else:

    A value is labelled "dBm" if and only if a valid calibration offset was
    actually added to it.

Requesting dBm on an uncalibrated frame therefore yields dBFS values, a dBFS
label, and a warning -- never a renamed dBFS number. Deliberately free of any
Qt import so the web layer, the backend logger and the tests can all use it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DBFS = "dBFS"
DBM = "dBm"
#: Centre frequency outside the measured calibration span: the offset is a
#: clamped endpoint value, not an interpolated one.
DBM_EXTRAPOLATED = "dBm*"

#: Delta/relative readouts are always plain dB -- the offset cancels in a
#: difference, so they are unit-invariant by construction.
DELTA_UNIT = "dB"

UNCALIBRATED_MESSAGE = (
    "Measurements are not calibrated yet - showing dBFS. Add a power "
    "calibration for this device and serial to display dBm (see calibration.md)."
)

EXTRAPOLATED_MESSAGE = (
    "Centre frequency is outside the measured calibration span; the dBm "
    "offset is extrapolated (shown as dBm*)."
)


@dataclass(frozen=True)
class UnitResolution:
    """Immutable per-frame resolution of the requested unit."""

    requested: str          # DBFS or DBM -- what the operator asked for
    unit: str               # DBFS, DBM or DBM_EXTRAPOLATED -- what is shown
    offset_db: float        # dB to ADD to raw dBFS to obtain the shown value
    calibrated: bool        # True only when offset_db was actually resolved
    warning: str            # "" when nothing is wrong

    @property
    def is_dbm(self) -> bool:
        return self.unit in (DBM, DBM_EXTRAPOLATED)

    @property
    def degraded(self) -> bool:
        """dBm was requested but could not be honoured."""
        return self.requested == DBM and not self.is_dbm

    def apply(self, dbfs):
        """Shift a scalar or a NumPy trace into the displayed unit."""
        if not self.offset_db:
            return dbfs
        return dbfs + self.offset_db

    def format(self, dbfs_value: float, decimals: int = 2) -> str:
        return f"{self.apply(float(dbfs_value)):.{decimals}f} {self.unit}"


def _get(frame, name, default):
    if frame is None:
        return default
    if isinstance(frame, dict):
        return frame.get(name, default)
    return getattr(frame, name, default)


def _clean_offset(raw) -> float | None:
    """Return a usable offset, or None for anything that is not a real number.

    A NaN or infinite offset means a corrupt calibration file, not a
    calibration; it must take the uncalibrated path rather than propagate NaN
    through the whole display chain.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def resolve(frame, requested: str) -> UnitResolution:
    """Resolve `requested` against one frame's calibration state.

    `frame` may be a SpectrumFrame, a decoded web header dict, or None (before
    the first frame arrives).
    """
    if requested != DBM:
        return UnitResolution(DBFS, DBFS, 0.0, False, "")

    calibrated = bool(_get(frame, "power_calibrated", False))
    offset = _clean_offset(_get(frame, "power_offset_db", None))

    if not calibrated or offset is None:
        return UnitResolution(DBM, DBFS, 0.0, False, UNCALIBRATED_MESSAGE)

    if bool(_get(frame, "power_in_cal_range", True)):
        return UnitResolution(DBM, DBM, offset, True, "")
    return UnitResolution(DBM, DBM_EXTRAPOLATED, offset, True, EXTRAPOLATED_MESSAGE)


def toggled(requested: str) -> str:
    """Return the other unit."""
    return DBFS if requested == DBM else DBM


class UnitState:
    """Owns the sticky operator choice; re-resolved against every frame.

    Register with `on_change()`; listeners fire only when the EFFECTIVE
    resolution changes, so relabelling a pyqtgraph axis and repolishing a
    stylesheet stay off the 30 Hz frame path -- that matters on a Pi.
    """

    def __init__(self, requested: str = DBFS):
        self._requested = requested if requested in (DBFS, DBM) else DBFS
        self._resolution = UnitResolution(self._requested, DBFS, 0.0, False, "")
        self._listeners: list = []

    # -- operator intent -------------------------------------------------
    @property
    def requested(self) -> str:
        return self._requested

    def set_requested(self, requested: str, frame=None) -> UnitResolution:
        if requested not in (DBFS, DBM):
            raise ValueError(f"Unknown amplitude unit: {requested}")
        self._requested = requested
        return self.update(frame, force=True)

    def toggle(self, frame=None) -> UnitResolution:
        return self.set_requested(toggled(self._requested), frame)

    # -- per-frame resolution --------------------------------------------
    @property
    def resolution(self) -> UnitResolution:
        return self._resolution

    @property
    def unit(self) -> str:
        return self._resolution.unit

    @property
    def offset_db(self) -> float:
        return self._resolution.offset_db

    @property
    def is_dbm(self) -> bool:
        return self._resolution.is_dbm

    def update(self, frame, force: bool = False) -> UnitResolution:
        new = resolve(frame, self._requested)
        if force or new != self._resolution:
            self._resolution = new
            for callback in self._listeners:
                callback(new)
        return self._resolution

    def apply(self, dbfs):
        return self._resolution.apply(dbfs)

    def format(self, value: float, decimals: int = 2) -> str:
        return self._resolution.format(value, decimals)

    def on_change(self, callback) -> None:
        self._listeners.append(callback)
"""Select amplitude fields from spectrum frames, honouring the unit choice.

Frames from `backend/controller.py` carry RAW dBFS traces plus a scalar
`power_offset_db`. Which unit is displayed is an operator decision held in
`frontend/units.py`, not a consequence of which attributes happen to exist.

`*_dbm` / `*_dbfs` lookups are retained because tests and older recordings
build frames that carry those explicit fields; live frames do not.
"""

from __future__ import annotations

from frontend.units import DBFS, DBM, UnitResolution, resolve

#: (calibrated field, raw field, legacy field) per logical trace.
TRACE_FIELDS = {
    "amplitude": ("amplitude_dbm", "amplitude_dbfs", "amplitude"),
    "max_hold": ("max_hold_dbm", "max_hold_dbfs", "max_hold"),
    "min_hold": ("min_hold_dbm", "min_hold_dbfs", "min_hold"),
    "average": ("average_dbm", "average_dbfs", "average"),
}


def _resolution(frame, unit_state) -> UnitResolution:
    """Accept a UnitState, a UnitResolution, a bare unit string, or None.

    None keeps the historical auto behaviour (dBm when the frame supplies an
    explicit dBm field) so callers that have not been migrated still work.
    """
    if unit_state is None:
        requested = DBM if getattr(frame, "amplitude_dbm", None) is not None else DBFS
        return resolve(frame, requested)
    if isinstance(unit_state, UnitResolution):
        return unit_state
    if isinstance(unit_state, str):
        return resolve(frame, unit_state)
    return unit_state.resolution


def amplitude_unit(frame, unit_state=None) -> str:
    """Unit valid for the values `trace_amplitude` will return."""
    return _resolution(frame, unit_state).unit


def trace_amplitude(frame, trace_name: str = "amplitude", unit_state=None):
    """Return one trace already expressed in the displayed unit.

    The dBm path prefers a precomputed `*_dbm` array; when the backend did not
    build one (the normal live case) it falls back to raw + offset, so a frame
    carrying only dBFS still displays correctly instead of raising.
    """
    try:
        dbm_field, dbfs_field, legacy_field = TRACE_FIELDS[trace_name]
    except KeyError as exc:
        raise ValueError(f"Unknown amplitude trace: {trace_name}") from exc

    res = _resolution(frame, unit_state)

    if res.is_dbm:
        value = getattr(frame, dbm_field, None)
        if value is not None:
            return value

    for field_name in (dbfs_field, legacy_field):
        value = getattr(frame, field_name, None)
        if value is not None:
            return res.apply(value) if res.is_dbm else value

    raise AttributeError(f"Frame has no values for {trace_name}")


def raw_trace(frame, trace_name: str = "amplitude"):
    """Return one trace in raw dBFS, whatever the display unit is.

    Used by anything that stores or exports rather than displays.
    """
    return trace_amplitude(frame, trace_name, DBFS)


def scalar_amplitude(frame, name: str, unit_state=None) -> float:
    """Same contract as `trace_amplitude`, for scalar measurements."""
    res = _resolution(frame, unit_state)

    if res.is_dbm:
        calibrated = getattr(frame, f"{name}_dbm", None)
        if calibrated is not None:
            return float(calibrated)

    raw = getattr(frame, f"{name}_dbfs", None)
    if raw is None:
        raw = getattr(frame, name, None)
    if raw is None:
        raise AttributeError(f"Frame has no value for {name}")
    return float(res.apply(float(raw)))


def peak_list(frame, unit_state=None):
    """Peaks in the displayed unit, or an empty list when there are none.

    Peak amplitudes are shifted rather than mutated in place: `Peak` instances
    belong to the frame, which the CSV exporter still needs in raw dBFS.
    """
    res = _resolution(frame, unit_state)

    if res.is_dbm:
        calibrated = getattr(frame, "peaks_dbm", None)
        if calibrated:
            return list(calibrated)

    peaks = getattr(frame, "peaks", None) or []
    if not res.is_dbm or not res.offset_db:
        return list(peaks)

    from dataclasses import replace

    shifted = []
    for peak in peaks:
        try:
            shifted.append(replace(peak, amplitude=float(peak.amplitude) + res.offset_db))
        except TypeError:
            shifted.append(peak)
    return shifted
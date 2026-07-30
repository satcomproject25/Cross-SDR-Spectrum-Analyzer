"""Continuous amplitude logging at user-selected carrier frequencies.

Design notes
------------
- Runs entirely on the GUI/frame-delivery thread: `on_frame()` is called once
  per displayed SpectrumFrame (~30 Hz) and only does work every LOG_INTERVAL_S
  seconds. No separate thread/timer is needed and there is no cross-thread
  state to guard.
- ONE CSV FILE PER CALENDAR DAY: data/logs/<YYYY>/<MM>/<DD>/<DD-MM-YYYY>.csv.
  Starting the logger multiple times on the same day appends to the same
  file rather than creating _1/_2/_3 files. Logging simply pauses when the
  session stops and resumes (appending) the next time it is started.
- Because different sessions on the same day may track different frequency
  sets, there is no single shared header row. Instead every session writes
  its own marker/header line:
      #SESSION#,<HH:MM:SS start time>,<freq1 label>,<freq2 label>,...
  followed by that session's data rows. This makes appending trivial (pure
  append-only, never a rewrite of existing content) and lets the plot
  dialog reconstruct exactly which columns applied to which rows, and where
  each session boundary falls, purely by re-reading the file top to bottom.
- Amplitude is read from the "average" trace (TraceEngine's running
  linear-power average), not the instantaneous clear-write/CW trace, so a
  10 s sample reflects the settled carrier level rather than one noisy FFT
  frame. average_dbm/average_dbfs is always populated on every SpectrumFrame
  regardless of whether the Average trace is checked on-screen.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

LOG_INTERVAL_S = 10.0
DEFAULT_LOG_ROOT = Path(__file__).resolve().parents[1] / "data" / "logs"

SESSION_MARKER = "#SESSION#"


class LoggerValidationError(ValueError):
    """Raised when a requested frequency is outside the current span."""


@dataclass(frozen=True)
class TrackedFrequency:
    requested_hz: float


def validate_frequency_in_span(
    frequency_hz: float, center_frequency_hz: float, span_hz: float
) -> None:
    """Raise LoggerValidationError unless frequency lies within the live span.

    Mirrors backend/dsp.py's own display-span crop (+/- span/2 about the
    center), so a frequency accepted here is guaranteed to land inside the
    bins the pipeline actually keeps.
    """
    half_span = span_hz / 2.0
    lower = center_frequency_hz - half_span
    upper = center_frequency_hz + half_span
    if not (lower <= frequency_hz <= upper):
        raise LoggerValidationError(
            f"{frequency_hz / 1e6:.6f} MHz is outside the current span "
            f"({lower / 1e6:.6f} - {upper / 1e6:.6f} MHz)."
        )


def _day_path(root: Path, now: datetime) -> Path:
    day_dir = root / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
    day_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = now.strftime("%d-%m-%Y")
    return day_dir / f"{date_stamp}.csv"


class AmplitudeLogger:
    """Owns the active daily CSV and samples amplitude from live frames.

    Usage:
        logger = AmplitudeLogger(log_root=...)
        logger.start(frequencies_hz=[915e6, 2440e6], unit="dBm")
        ...
        logger.on_frame(frame)   # call once per delivered SpectrumFrame
        ...
        logger.stop()
        # later the same day:
        logger.start(frequencies_hz=[915e6], unit="dBm")   # appends to same file
    """

    def __init__(self, log_root: Path | None = None):
        self.log_root = Path(log_root) if log_root is not None else DEFAULT_LOG_ROOT
        self._active = False
        self._frequencies: list[float] = []
        self._bin_indices: list[int] = []
        self._unit = "dBFS"
        self._path: Path | None = None
        self._last_log_monotonic = 0.0
        self._resolved = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def session_path(self) -> Path | None:
        return self._path

    @property
    def frequencies_hz(self) -> list[float]:
        return list(self._frequencies)

    def start(self, frequencies_hz: list[float], unit: str, now: datetime | None = None) -> Path:
        if self._active:
            raise RuntimeError("Logger session already active; call stop() first")
        if len(frequencies_hz) < 1:
            raise ValueError("Provide at least one frequency")

        now = now or datetime.now()
        path = _day_path(self.log_root, now)

        session_header = [SESSION_MARKER, now.strftime("%H:%M:%S")] + [
            f"{freq / 1e6:.6f} MHz ({unit})" for freq in frequencies_hz
        ]
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(session_header)

        self._frequencies = list(frequencies_hz)
        self._bin_indices = [None] * len(frequencies_hz)  # resolved on first frame
        self._unit = unit
        self._path = path
        self._active = True
        self._resolved = False
        # Force an immediate sample on the next frame rather than waiting a
        # full interval, so the user sees the first row right after pressing OK.
        self._last_log_monotonic = 0.0
        return path

    def stop(self) -> None:
        self._active = False
        self._path = None
        self._frequencies = []
        self._bin_indices = []
        self._resolved = False

    def on_frame(self, frame) -> bool:
        """Sample and append a row if LOG_INTERVAL_S has elapsed. Returns True if a row was written."""
        if not self._active:
            return False

        now_monotonic = time.monotonic()
        if now_monotonic - self._last_log_monotonic < LOG_INTERVAL_S:
            return False

        from frontend.amplitude import trace_amplitude  # local import: avoid Qt at module load

        frequency_axis = np.asarray(frame.frequency)
        amplitude = np.asarray(trace_amplitude(frame, "average"))

        if not self._resolved:
            self._bin_indices = [
                int(np.argmin(np.abs(frequency_axis - target)))
                for target in self._frequencies
            ]
            self._resolved = True

        values = []
        for index in self._bin_indices:
            index = min(index, amplitude.size - 1)
            values.append(float(amplitude[index]))

        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self._path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp] + [f"{v:.3f}" for v in values])

        self._last_log_monotonic = now_monotonic
        return True

    # -- browsing helpers for the plot dialog --------------------------------
    def available_years(self) -> list[str]:
        if not self.log_root.exists():
            return []
        return sorted(p.name for p in self.log_root.iterdir() if p.is_dir())

    def available_months(self, year: str) -> list[str]:
        year_dir = self.log_root / year
        if not year_dir.exists():
            return []
        return sorted(p.name for p in year_dir.iterdir() if p.is_dir())

    def available_days(self, year: str, month: str) -> list[str]:
        month_dir = self.log_root / year / month
        if not month_dir.exists():
            return []
        return sorted(p.name for p in month_dir.iterdir() if p.is_dir())

    def day_file(self, year: str, month: str, day: str) -> Path | None:
        """Return the single CSV file for a given day, if it exists."""
        day_dir = self.log_root / year / month / day
        if not day_dir.exists():
            return None
        matches = sorted(day_dir.glob("*.csv"))
        return matches[0] if matches else None

    @staticmethod
    def read_day_file(
        path: Path,
    ) -> tuple[list[str], list[str], list[list[float]], list[int]]:
        """Parse one day's CSV, concatenating every session in file order.

        Returns:
            timestamps: HH:MM:SS strings, one per logged data row, across
                every session in the file (session marker rows excluded).
            column_labels: frequency-column labels, in first-seen order
                (union across all sessions in the file).
            columns: columns[i] holds one frequency-column's amplitude
                values. Because different sessions can log different
                frequency sets, this uses the UNION of all column labels
                seen in the file; rows from a session that didn't track a
                given column are filled with NaN so every column stays
                aligned index-for-index with `timestamps`.
            session_boundaries: row indices (into `timestamps`) where a new
                session began, for the plot dialog to draw divider lines.
                Index 0 (the very first session) is included.
        """
        column_labels: list[str] = []
        column_index_by_label: dict[str, int] = {}
        timestamps: list[str] = []
        columns: list[list[float]] = []
        session_boundaries: list[int] = []

        current_session_columns: list[int] = []  # column index for each position in the active session's header

        with open(path, newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                if row[0] == SESSION_MARKER:
                    session_boundaries.append(len(timestamps))
                    labels = row[2:]
                    current_session_columns = []
                    for label in labels:
                        if label not in column_index_by_label:
                            column_index_by_label[label] = len(column_labels)
                            column_labels.append(label)
                            # Backfill NaN for every row already seen so this
                            # new column stays aligned with `timestamps`.
                            columns.append([float("nan")] * len(timestamps))
                        current_session_columns.append(column_index_by_label[label])
                    continue

                # Data row: pad every existing column for this row first
                # (covers columns this session doesn't track), then fill in
                # the ones it does.
                row_index = len(timestamps)
                timestamps.append(row[0])
                for column in columns:
                    column.append(float("nan"))
                for position, raw_value in enumerate(row[1:]):
                    if position >= len(current_session_columns):
                        break
                    column_index = current_session_columns[position]
                    try:
                        columns[column_index][row_index] = float(raw_value)
                    except ValueError:
                        columns[column_index][row_index] = float("nan")

        return timestamps, column_labels, columns, session_boundaries
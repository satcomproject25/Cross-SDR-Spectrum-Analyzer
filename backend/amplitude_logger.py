"""Continuous amplitude logging at up to two user-selected carrier frequencies.

Design notes
------------
- Runs entirely on the GUI/frame-delivery thread: `on_frame()` is called once
  per displayed SpectrumFrame (~30 Hz) and only does work every LOG_INTERVAL_S
  seconds. No separate thread/timer is needed and there is no cross-thread
  state to guard.
- One CSV file per acquisition *session* (start Logger -> stop/close app).
  If the app is started/stopped multiple times on the same calendar day, each
  session gets its own file: <DD-MM-YYYY>_1.csv, <DD-MM-YYYY>_2.csv, ...
- Files are organized as data/logs/<YYYY>/<MM>/<DD>/<DD-MM-YYYY>_<N>.csv so a
  day's sessions are easy to find and the plotting dialog can browse by
  Year -> Month -> Day.
- Amplitude is read from whichever calibrated field the rest of the app is
  currently displaying (dBm if calibrated, dBFS otherwise) so logged values
  always match the on-screen unit. The unit actually used is written into the
  CSV header so a later dBm/dBFS switch (e.g. recalibration) can't silently
  mix units inside one file.
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

LOG_INTERVAL_S = 10.0
MAX_TRACKED_FREQUENCIES = 2
DEFAULT_LOG_ROOT = Path(__file__).resolve().parents[1] / "data" / "logs"

_SESSION_FILENAME_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})_(\d+)\.csv$")


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


def _existing_session_indices(day_dir: Path, date_stamp: str) -> list[int]:
    if not day_dir.exists():
        return []
    indices = []
    for entry in day_dir.iterdir():
        match = _SESSION_FILENAME_RE.match(entry.name)
        if match and match.group(1) == date_stamp:
            indices.append(int(match.group(2)))
    return indices


def _next_session_path(root: Path, now: datetime) -> Path:
    day_dir = root / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
    date_stamp = now.strftime("%d-%m-%Y")
    existing = _existing_session_indices(day_dir, date_stamp)
    next_index = max(existing, default=0) + 1
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{date_stamp}_{next_index}.csv"


class AmplitudeLogger:
    """Owns one active CSV session and samples amplitude from live frames.

    Usage:
        logger = AmplitudeLogger(log_root=...)
        logger.start(frequencies_hz=[915e6, 2440e6], unit="dBm")
        ...
        logger.on_frame(frame)   # call once per delivered SpectrumFrame
        ...
        logger.stop()
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
        if not (1 <= len(frequencies_hz) <= MAX_TRACKED_FREQUENCIES):
            raise ValueError(
                f"Provide between 1 and {MAX_TRACKED_FREQUENCIES} frequencies"
            )

        now = now or datetime.now()
        path = _next_session_path(self.log_root, now)

        header = ["timestamp"] + [
            f"{freq / 1e6:.6f} MHz ({unit})" for freq in frequencies_hz
        ]
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)

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
        amplitude = np.asarray(trace_amplitude(frame, "amplitude"))

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

    def sessions_for_day(self, year: str, month: str, day: str) -> list[Path]:
        day_dir = self.log_root / year / month / day
        if not day_dir.exists():
            return []
        return sorted(
            day_dir.glob("*.csv"),
            key=lambda p: int(_SESSION_FILENAME_RE.match(p.name).group(2))
            if _SESSION_FILENAME_RE.match(p.name)
            else 0,
        )

    @staticmethod
    def read_session(
        path: Path,
    ) -> tuple[list[str], list[str], list[list[float]]]:
        """Return (timestamps, frequency_column_labels, columns).

        `columns[i]` is one frequency's list of amplitude values, aligned
        index-for-index with `timestamps` (both are per logged row, HH:MM:SS).
        """
        with open(path, newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            freq_labels = header[1:]
            columns: list[list[float]] = [[] for _ in freq_labels]
            timestamps: list[str] = []
            for row in reader:
                if not row:
                    continue
                timestamps.append(row[0])
                for i, raw_value in enumerate(row[1:]):
                    try:
                        columns[i].append(float(raw_value))
                    except ValueError:
                        columns[i].append(float("nan"))
        return timestamps, freq_labels, columns
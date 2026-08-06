"""Screenshot and CSV export.

Export policy is deliberately NOT tied to the display unit switch:

  * raw `*_dbfs` columns are ALWAYS written -- a calibration found to be wrong
    six months later is unrecoverable from a dBm-only file, but trivially
    re-derived from one holding both;
  * `*_dbm` columns are written whenever a valid offset exists, regardless of
    what the screen currently shows;
  * a `#` provenance preamble records the offset and the requested unit.
"""

import csv
import os
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtWidgets import QWidget, QFileDialog, QMessageBox

from frontend.units import DBM, resolve

DEFAULT_EXPORT_DIR = os.path.join(os.path.expanduser("~"), "SpectrumAnalyzer_Exports")


class Recorder:
    def __init__(self, main_window: QWidget):
        self.main_window = main_window
        os.makedirs(DEFAULT_EXPORT_DIR, exist_ok=True)

    def take_screenshot(self, target_widget: Optional[QWidget] = None) -> Optional[str]:
        widget = target_widget or self.main_window
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(DEFAULT_EXPORT_DIR, f"spectrum_{timestamp}.png")
        path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save Screenshot", default_path, "PNG Files (*.png)"
        )
        if not path:
            return None
        pixmap = widget.grab()
        success = pixmap.save(path, "PNG")
        if not success:
            QMessageBox.warning(
                self.main_window, "Screenshot Failed",
                f"Could not save screenshot to:\n{path}",
            )
            return None
        return path

    def export_csv(self, frame, requested_unit: str = None) -> Optional[str]:
        if frame is None:
            QMessageBox.warning(
                self.main_window, "Export Failed",
                "No spectrum data available to export yet.",
            )
            return None

        if requested_unit is None:
            state = getattr(self.main_window, "unit_state", None)
            requested_unit = state.requested if state is not None else DBM

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(DEFAULT_EXPORT_DIR, f"spectrum_{timestamp}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export CSV", default_path, "CSV Files (*.csv)"
        )
        if not path:
            return None

        # Resolve against dBm unconditionally: the file records what CAN be
        # calibrated, independently of what the screen is showing right now.
        cal = resolve(frame, DBM)

        frequency = frame.frequency
        header = ["frequency_hz"]
        columns = [frequency]

        raw_fields = (
            ("amplitude_dbfs", "amplitude"),
            ("max_hold_dbfs", "max_hold"),
            ("min_hold_dbfs", "min_hold"),
            ("average_dbfs", "average"),
        )
        raw_present = []
        for header_name, legacy_name in raw_fields:
            values = getattr(frame, header_name, None)
            if values is None:
                values = getattr(frame, legacy_name, None)
            if values is not None:
                header.append(header_name)
                columns.append(values)
                raw_present.append((header_name, values))

        if cal.calibrated:
            for header_name, raw_values in raw_present:
                dbm_name = header_name.replace("_dbfs", "_dbm")
                values = getattr(frame, dbm_name, None)
                if values is None:
                    values = cal.apply(raw_values)
                header.append(dbm_name)
                columns.append(values)

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        preamble = [
            f"# exported_utc={stamp}",
            f"# display_unit_requested={requested_unit}",
            f"# power_calibrated={cal.calibrated}",
            f"# power_offset_db={cal.offset_db if cal.calibrated else 'null'}",
            f"# power_in_cal_range={getattr(frame, 'power_in_cal_range', True)}",
            f"# center_frequency_hz={getattr(frame, 'center_frequency', '')}",
            f"# sample_rate_hz={getattr(frame, 'sample_rate', '')}",
            f"# rbw_hz={getattr(frame, 'rbw', '')}",
        ]
        if not cal.calibrated:
            preamble.append(
                "# NOTE: no valid power calibration; dBm columns intentionally omitted"
            )

        try:
            with open(path, "w", newline="") as f:
                for line in preamble:
                    f.write(line + "\n")
                writer = csv.writer(f)
                writer.writerow(header)
                for row in zip(*columns):
                    writer.writerow(row)
        except OSError as e:
            QMessageBox.warning(self.main_window, "Export Failed", str(e))
            return None

        if requested_unit == DBM and not cal.calibrated:
            QMessageBox.information(
                self.main_window, "Exported without dBm",
                "This device has no valid power calibration, so only dBFS "
                "columns were written.",
            )
        return path
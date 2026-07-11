import csv
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QWidget, QFileDialog, QMessageBox

DEFAULT_EXPORT_DIR = os.path.join(os.path.expanduser("~"), "SpectrumAnalyzer_Exports")


class Recorder:
    def __init__(self, main_window: QWidget):
        self.main_window = main_window
        os.makedirs(DEFAULT_EXPORT_DIR, exist_ok=True)

    def take_screenshot(self, target_widget: Optional[QWidget] = None) -> Optional[str]:
        widget = target_widget or self.main_window
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(DEFAULT_EXPORT_DIR, f"spectrum_{timestamp}.png")
        path, _ = QFileDialog.getSaveFileName(self.main_window, "Save Screenshot", default_path, "PNG Files (*.png)")
        if not path:
            return None
        pixmap = widget.grab()
        success = pixmap.save(path, "PNG")
        if not success:
            QMessageBox.warning(self.main_window, "Screenshot Failed", f"Could not save screenshot to:\n{path}")
            return None
        return path

    def export_csv(self, frame) -> Optional[str]:
        if frame is None:
            QMessageBox.warning(self.main_window, "Export Failed", "No spectrum data available to export yet.")
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(DEFAULT_EXPORT_DIR, f"spectrum_{timestamp}.csv")
        path, _ = QFileDialog.getSaveFileName(self.main_window, "Export CSV", default_path, "CSV Files (*.csv)")
        if not path:
            return None
        frequency = frame.frequency
        amplitude = frame.amplitude
        header = ["frequency_hz", "amplitude_dbfs"]
        columns = [frequency, amplitude]
        if getattr(frame, "max_hold", None) is not None:
            header.append("max_hold_dbfs")
            columns.append(frame.max_hold)
        if getattr(frame, "min_hold", None) is not None:
            header.append("min_hold_dbfs")
            columns.append(frame.min_hold)
        if getattr(frame, "average", None) is not None:
            header.append("average_dbfs")
            columns.append(frame.average)
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                for row in zip(*columns):
                    writer.writerow(row)
        except OSError as e:
            QMessageBox.warning(self.main_window, "Export Failed", str(e))
            return None
        return path

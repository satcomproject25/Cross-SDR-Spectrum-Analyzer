"""Calibration tab: download a blank workbook, upload a filled one.

Self-contained. The only thing gui.py must do is construct it and add it as a
tab; see the integration patch. It reads the connected device identity through
an optional callable so it never imports from gui.py (no circular import).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from backend.cal_workbook import apply_workbook, build_template, template_filename
from backend.calibration import PowerCalibration, load_device_calibration

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "SpectrumAnalyzer_Exports")


class CalibrationPanel(QWidget):
    """Download / fill / upload calibration workflow."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        device_info: Callable[[], tuple[str, str]] | None = None,
        on_applied: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._device_info = device_info or (lambda: ("HACKRF", ""))
        self._on_applied = on_applied
        os.makedirs(DEFAULT_DIR, exist_ok=True)
        self._build()
        self.refresh_status()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        grp_status = QGroupBox("Current Calibration")
        status_layout = QVBoxLayout(grp_status)
        self.lbl_status = QLabel("Checking...")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setFont(QFont("Consolas", 9))
        self.lbl_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_layout.addWidget(self.lbl_status)
        layout.addWidget(grp_status)

        grp_actions = QGroupBox("Calibration Workbook")
        actions_layout = QVBoxLayout(grp_actions)

        hint = QLabel(
            "1. Download the workbook.  2. Fill the yellow cells while sweeping a known "
            "signal generator.  3. Upload it back here. The offsets are solved and written "
            "automatically; restart acquisition afterwards."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999999;")
        actions_layout.addWidget(hint)

        buttons = QHBoxLayout()
        self.btn_download = QPushButton("Download Template")
        self.btn_upload = QPushButton("Upload Filled Workbook")
        for button in (self.btn_download, self.btn_upload):
            button.setMinimumHeight(38)
            buttons.addWidget(button)
        actions_layout.addLayout(buttons)

        self.btn_reload = QPushButton("Reload calibration.json")
        self.btn_reload.setMinimumHeight(30)
        actions_layout.addWidget(self.btn_reload)
        layout.addWidget(grp_actions)

        grp_report = QGroupBox("Solver Report")
        report_layout = QVBoxLayout(grp_report)
        self.txt_report = QPlainTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setFont(QFont("Consolas", 9))
        self.txt_report.setMinimumHeight(220)
        self.txt_report.setPlaceholderText("Upload a workbook to see the solver output here.")
        report_layout.addWidget(self.txt_report)
        layout.addWidget(grp_report, 1)

        self.btn_download.clicked.connect(self.download_template)
        self.btn_upload.clicked.connect(self.upload_workbook)
        self.btn_reload.clicked.connect(self.refresh_status)

    # -- status ------------------------------------------------------------
    def refresh_status(self) -> None:
        device_type, serial = self._device_info()
        cal = load_device_calibration(device_type, serial)
        power = PowerCalibration.from_calibration(cal)

        lines = [f"Device      {device_type}  serial {serial or '(default)'}"]

        fixed = float(cal.get("frequency_axis_offset_hz") or 0.0)
        ppm = float(cal.get("ppm_offset") or 0.0)
        table = cal.get("frequency_offset_table") or []
        if fixed or ppm or table:
            detail = f"fixed {fixed:+.0f} Hz, {ppm:+.3f} ppm"
            if table:
                detail += f", +{len(table)}-point residual table"
            lines.append(f"Frequency   CALIBRATED  ({detail})")
        else:
            lines.append("Frequency   not calibrated")

        if power.base_table:
            low, high = power.frequency_range_hz
            lines.append(
                f"Power       CALIBRATED  ({len(power.base_table)} points, "
                f"{low/1e6:.0f}-{high/1e6:.0f} MHz, ref gain {power.reference_gain_db:g} dB)"
            )
            if len(power.gain_table) > 1:
                deviating = [
                    f"{p['gain_db']:g}:{p['delta_db']:+.1f}"
                    for p in power.gain_table
                    if abs(p["delta_db"]) >= 0.1
                ]
                lines.append(
                    "Gain table  " + (", ".join(deviating) if deviating else "all gains nominal")
                )
            else:
                lines.append(f"Gain table  single gain only ({power.reference_gain_db:g} dB)")
        elif power.legacy_offset_db is not None:
            lines.append(f"Power       single fixed offset {power.legacy_offset_db:+.2f} dB")
        else:
            lines.append("Power       not calibrated - amplitudes remain dBFS")

        meta = power.metadata or {}
        if meta.get("calibrated_at"):
            lines.append(f"Last run    {meta['calibrated_at']}  by {meta.get('operator') or 'unknown'}")

        self.lbl_status.setText("\n".join(lines))

    # -- actions -----------------------------------------------------------
    def download_template(self) -> None:
        device_type, serial = self._device_info()
        default = os.path.join(DEFAULT_DIR, template_filename(device_type, serial))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration Template", default, "Excel Workbook (*.xlsx)"
        )
        if not path:
            return
        try:
            Path(path).write_bytes(build_template(device_type, serial))
        except OSError as exc:
            QMessageBox.warning(self, "Download Failed", str(exc))
            return
        self.txt_report.setPlainText(
            f"Template saved to:\n{path}\n\n"
            "Fill the yellow cells on SETUP, FREQ_CAL and POWER_CAL, then use "
            "'Upload Filled Workbook'. Read the README sheet first: the attenuator "
            "pad and the 15-minute warm-up matter more than the number of points."
        )
        QMessageBox.information(self, "Template Saved", f"Saved to:\n{path}")

    def upload_workbook(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload Filled Calibration Workbook", DEFAULT_DIR, "Excel Workbook (*.xlsx)"
        )
        if not path:
            return

        result = apply_workbook(path)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.txt_report.setPlainText(f"[{stamp}] {Path(path).name}\n\n{result.report()}")

        if not result.ok:
            QMessageBox.warning(
                self,
                "Calibration Not Applied",
                "The workbook could not be used:\n\n" + "\n".join(result.errors),
            )
            return

        self.refresh_status()
        if self._on_applied:
            self._on_applied()

        message = (
            f"Calibration written for {result.device_type}"
            f"{' / ' + result.serial if result.serial else ''}.\n\n"
            f"Frequency points: {result.freq_points}\n"
            f"Power points: {result.power_points}\n"
            f"Rejected rows: {len(result.rejected_rows)}\n\n"
            "Restart acquisition for it to take effect."
        )
        if result.warnings:
            message += f"\n\n{len(result.warnings)} warning(s) - see the solver report."
        QMessageBox.information(self, "Calibration Applied", message)
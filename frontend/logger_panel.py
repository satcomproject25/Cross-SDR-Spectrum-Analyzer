"""
logger_panel.py
---------------
GUI dialogs for the amplitude logging feature:
  - LoggerSetupDialog: enter any number of carrier frequencies (starts with
    2 rows, "+ Add frequency" appends more). The dialog grows to fit its
    rows instead of scrolling, up to a sane cap, after which it switches to
    a scroll area so an extreme number of rows can't push it off-screen.
    Every frequency is validated against the live span before OK.
  - LoggerPlotDialog: browse Year -> Month -> Day and plot a day's logged
    amplitude columns vs time, with zoom/pan, a reset-view button, a live
    cursor readout, and thin vertical red lines marking session boundaries
    within that day's file.

Owner: Developer B (Frontend/GUI)
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from backend.amplitude_logger import AmplitudeLogger, LoggerValidationError, validate_frequency_in_span

# Colors matched to frontend/gui.py's _apply_dark_theme() palette so both
# dialogs read as part of the same application rather than a bolted-on tool.
COLOR_BACKGROUND = "#000000"
COLOR_PANEL = "#0A0A0A"
COLOR_PANEL_RAISED = "#111111"
COLOR_BORDER = "#363636"
COLOR_BORDER_STRONG = "#484848"
COLOR_TEXT = "#F2F2F2"
COLOR_MUTED_TEXT = "#B8B8B8"
COLOR_SECTION_TEXT = "#8DEEFF"
COLOR_AXIS_TEXT = "#CCCCCC"
COLOR_ACCENT = "#33D6EE"
COLOR_ACCENT_TEXT = "#8DEEFF"
COLOR_ERROR = "#FF6B6B"
COLOR_SESSION_LINE = "#E23636"

# Cycled across however many frequencies are tracked in a session.
TRACE_COLORS = [
    "#00F0FF", "#FF7F00", "#B45CFF", "#FFD60A", "#5FD791", "#FF4FD8",
]

# Row badge colors, cycled the same way so a row's number visually matches
# the color its trace will eventually be plotted in.
BADGE_TEXT_COLORS = TRACE_COLORS

DIALOG_STYLESHEET = f"""
    QDialog {{
        background-color: {COLOR_BACKGROUND};
    }}
    QWidget {{
        color: {COLOR_TEXT};
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 10pt;
    }}
    QLabel {{
        color: {COLOR_TEXT};
        background: transparent;
    }}
    QLabel#DialogTitle {{
        color: {COLOR_SECTION_TEXT};
        font-size: 12pt;
        font-weight: 700;
    }}
    QLabel#DialogInfo {{
        color: {COLOR_MUTED_TEXT};
    }}
    QLabel#RowError {{
        color: {COLOR_ERROR};
        font-weight: 600;
    }}
    QLabel#SectionLabel {{
        color: {COLOR_MUTED_TEXT};
        font-size: 8pt;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QLabel#CursorReadout {{
        color: {COLOR_SECTION_TEXT};
        background: {COLOR_PANEL};
        border: 1px solid {COLOR_BORDER};
        border-radius: 6px;
        padding: 6px 10px;
    }}
    QPushButton {{
        background-color: #171717;
        border: 1px solid {COLOR_BORDER_STRONG};
        padding: 8px 13px;
        border-radius: 6px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: #262626; border-color: {COLOR_ACCENT}; }}
    QPushButton:pressed {{ background-color: #0F0F0F; }}
    QPushButton#AddFrequencyButton {{
        background: #0B353C;
        border-color: {COLOR_ACCENT};
        color: {COLOR_ACCENT_TEXT};
        font-weight: 700;
        padding: 9px 16px;
    }}
    QPushButton#RemoveFrequencyButton {{
        background: #2A1414;
        border-color: #7A2E2E;
        color: #FFB3B3;
        font-weight: 700;
        max-width: 30px;
        min-width: 30px;
        max-height: 30px;
        min-height: 30px;
        padding: 0px;
        border-radius: 15px;
    }}
    QPushButton#OkButton {{
        background: #0F4C3A;
        border-color: #1B7A5C;
        color: #8FF0C7;
        padding: 9px 22px;
    }}
    QPushButton#ToolButton {{
        max-width: 34px;
        min-width: 34px;
        max-height: 34px;
        min-height: 34px;
        padding: 0px;
        font-size: 13pt;
    }}
    QDoubleSpinBox, QComboBox {{
        background-color: {COLOR_PANEL_RAISED};
        border: 1px solid {COLOR_BORDER_STRONG};
        padding: 7px 9px;
        border-radius: 6px;
        selection-background-color: #0B5664;
    }}
    QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {COLOR_ACCENT}; }}
    QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {COLOR_ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: #101010;
        color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER_STRONG};
        selection-background-color: #0B5664;
        selection-color: #FFFFFF;
    }}
    QFrame#FrequencyRow {{
        background-color: {COLOR_PANEL};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
    }}
    QFrame#FrequencyRow:hover {{
        border-color: #4A4A4A;
    }}
    QFrame#HeaderRule {{
        background-color: {COLOR_BORDER};
        max-height: 1px;
        min-height: 1px;
    }}
    QFrame#ToolbarCard {{
        background-color: {COLOR_PANEL};
        border: 1px solid {COLOR_BORDER};
        border-radius: 9px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: {COLOR_BACKGROUND};
        width: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #333333;
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #45D9F2; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""

# Rows fit naturally (dialog grows) up to this many; beyond it, the row
# list becomes internally scrollable so the dialog can't grow off-screen.
MAX_UNSCROLLED_ROWS = 6
ROW_HEIGHT_PX = 52


class _FrequencyRow(QFrame):
    """One numbered 'badge | [ frequency MHz ] | remove' card."""

    def __init__(self, index: int, initial_mhz: float, removable: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("FrequencyRow")
        self.index = index

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.badge = QLabel()
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(6)
        self.spin.setRange(0.0, 6000.0)
        self.spin.setSuffix(" MHz")
        self.spin.setValue(initial_mhz)
        self.spin.setMinimumWidth(180)
        self.spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.remove_button = QPushButton("\u2715")  # small x
        self.remove_button.setObjectName("RemoveFrequencyButton")
        self.remove_button.setVisible(removable)
        self.remove_button.setToolTip("Remove this frequency")

        layout.addWidget(self.badge)
        layout.addWidget(self.spin, 1)
        layout.addWidget(self.remove_button)

        self.setMinimumHeight(ROW_HEIGHT_PX)
        self._apply_badge_color()

    def _apply_badge_color(self):
        color = BADGE_TEXT_COLORS[self.index % len(BADGE_TEXT_COLORS)]
        self.badge.setText(str(self.index + 1))
        self.badge.setStyleSheet(
            f"QLabel {{ background: {COLOR_PANEL_RAISED}; color: {color}; "
            f"border: 1px solid {color}; border-radius: 13px; font-weight: 700; }}"
        )

    def set_index(self, index: int):
        self.index = index
        self._apply_badge_color()

    def frequency_hz(self) -> float:
        return self.spin.value() * 1e6


class LoggerSetupDialog(QDialog):
    """Modal dialog to collect any number of frequencies to log.

    Starts with 2 rows; "+ Add frequency" adds more, the small x removes a
    row (down to a minimum of 1). The dialog grows to accommodate new rows
    up to MAX_UNSCROLLED_ROWS, beyond which the row list scrolls internally
    instead of pushing the window off-screen. Every frequency is validated
    against the current span before OK is accepted.
    """

    def __init__(self, center_frequency_hz: float, span_hz: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude Logger")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(DIALOG_STYLESHEET)
        self._center_frequency_hz = center_frequency_hz
        self._span_hz = span_hz
        self._result_frequencies: list[float] | None = None
        self._rows: list[_FrequencyRow] = []

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 18, 20, 18)
        outer_layout.setSpacing(12)

        title = QLabel("Track Carrier Frequencies")
        title.setObjectName("DialogTitle")
        outer_layout.addWidget(title)

        lower_mhz = (center_frequency_hz - span_hz / 2) / 1e6
        upper_mhz = (center_frequency_hz + span_hz / 2) / 1e6
        info = QLabel(
            "Every frequency below is logged every 10 s while active. All "
            f"values must fall within the current span, {lower_mhz:.6f} - "
            f"{upper_mhz:.6f} MHz."
        )
        info.setObjectName("DialogInfo")
        info.setWordWrap(True)
        outer_layout.addWidget(info)

        rule = QFrame()
        rule.setObjectName("HeaderRule")
        outer_layout.addWidget(rule)

        section_label = QLabel("FREQUENCIES")
        section_label.setObjectName("SectionLabel")
        outer_layout.addWidget(section_label)

        # Rows live in a QVBoxLayout that grows naturally with the dialog.
        # Only once there are more rows than MAX_UNSCROLLED_ROWS does the
        # container get capped and start scrolling, so a normal 2-6
        # frequency session never shows a scrollbar at all.
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)

        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setWidget(self.rows_container)
        self.rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(self.rows_scroll)

        add_row_layout = QHBoxLayout()
        self.add_button = QPushButton("+  Add frequency")
        self.add_button.setObjectName("AddFrequencyButton")
        add_row_layout.addWidget(self.add_button)
        add_row_layout.addStretch(1)
        outer_layout.addLayout(add_row_layout)

        self.error_label = QLabel("")
        self.error_label.setObjectName("RowError")
        self.error_label.setWordWrap(True)
        self.error_label.setMinimumHeight(18)
        outer_layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.ok_button = QPushButton("OK")
        self.ok_button.setObjectName("OkButton")
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        outer_layout.addLayout(buttons)

        self.add_button.clicked.connect(self._add_row)
        self.ok_button.clicked.connect(self._on_ok)
        self.cancel_button.clicked.connect(self.reject)

        # Start with 2 rows, as before, but now backed by the same
        # add/remove machinery as every later row.
        self._add_row(initial_mhz=center_frequency_hz / 1e6)
        self._add_row(initial_mhz=0.0)
        self._sync_container_height()

    def _add_row(self, initial_mhz: float = 0.0):
        row = _FrequencyRow(
            index=len(self._rows), initial_mhz=initial_mhz, removable=True, parent=self.rows_container
        )
        row.remove_button.clicked.connect(lambda: self._remove_row(row))
        self._rows.append(row)
        self.rows_layout.addWidget(row)
        self._sync_remove_visibility()
        self._sync_container_height()

    def _remove_row(self, row: _FrequencyRow):
        if len(self._rows) <= 1:
            return
        self._rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        for index, remaining_row in enumerate(self._rows):
            remaining_row.set_index(index)
        self._sync_remove_visibility()
        self._sync_container_height()

    def _sync_remove_visibility(self):
        only_row = len(self._rows) == 1
        for row in self._rows:
            row.remove_button.setVisible(not only_row)

    def _sync_container_height(self):
        """Let the dialog grow with the row count, up to a visible cap.

        Below MAX_UNSCROLLED_ROWS the scroll area's max height tracks the
        exact content height (no scrollbar, no empty space -- the dialog
        itself just gets taller). At or above the cap, height is pinned so
        the row list scrolls internally instead of growing indefinitely.
        """
        row_count = len(self._rows)
        content_height = row_count * ROW_HEIGHT_PX + max(0, row_count - 1) * self.rows_layout.spacing()
        capped_height = MAX_UNSCROLLED_ROWS * ROW_HEIGHT_PX + (MAX_UNSCROLLED_ROWS - 1) * self.rows_layout.spacing()
        target_height = min(content_height, capped_height)
        self.rows_scroll.setMinimumHeight(target_height)
        self.rows_scroll.setMaximumHeight(target_height)
        # Let Qt recompute the dialog's natural size around the new content
        # height instead of leaving stale extra space or clipping rows.
        self.adjustSize()

    def _on_ok(self):
        frequencies_hz = [row.frequency_hz() for row in self._rows if row.frequency_hz() > 0.0]
        if not frequencies_hz:
            self.error_label.setText("Enter at least one frequency greater than 0 MHz.")
            return

        try:
            for freq in frequencies_hz:
                validate_frequency_in_span(
                    freq, self._center_frequency_hz, self._span_hz
                )
        except LoggerValidationError as exc:
            self.error_label.setText(str(exc))
            return

        self._result_frequencies = frequencies_hz
        self.accept()

    def result_frequencies_hz(self) -> list[float] | None:
        return self._result_frequencies


class LoggerPlotDialog(QDialog):
    """Browse Year/Month/Day and plot that day's logged amplitude columns.

    Since logging writes one CSV per calendar day (every start/stop session,
    including ones that roll over midnight, appends to the same file), there
    is no separate "session" selector -- picking a day plots its entire
    file, with thin vertical red lines marking where each individual
    session began.
    """

    def __init__(self, logger: AmplitudeLogger, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude Logger - Plot Recorded Day")
        self.setStyleSheet(DIALOG_STYLESHEET)
        self.resize(980, 620)
        self._logger = logger
        self._timestamps: list[str] = []
        self._crosshair_v = None
        self._crosshair_h = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Recorded Amplitude History")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        toolbar = QFrame()
        toolbar.setObjectName("ToolbarCard")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(8)

        for label_text, combo_name in (("Year", "year_combo"), ("Month", "month_combo"), ("Day", "day_combo")):
            label = QLabel(label_text + ":")
            label.setObjectName("SectionLabel")
            toolbar_layout.addWidget(label)
            combo = QComboBox()
            combo.setMinimumWidth(90)
            setattr(self, combo_name, combo)
            toolbar_layout.addWidget(combo)

        self.plot_button = QPushButton("Plot")
        toolbar_layout.addWidget(self.plot_button)

        toolbar_layout.addSpacing(12)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet(f"color: {COLOR_BORDER_STRONG};")
        toolbar_layout.addWidget(separator)
        toolbar_layout.addSpacing(4)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("ToolButton")
        self.zoom_in_button.setToolTip("Zoom in")
        self.zoom_out_button = QPushButton("\u2212")
        self.zoom_out_button.setObjectName("ToolButton")
        self.zoom_out_button.setToolTip("Zoom out")
        self.reset_view_button = QPushButton("\u21BB")
        self.reset_view_button.setObjectName("ToolButton")
        self.reset_view_button.setToolTip("Reset zoom / pan")
        for button in (self.zoom_in_button, self.zoom_out_button, self.reset_view_button):
            toolbar_layout.addWidget(button)

        toolbar_layout.addStretch(1)
        self.cursor_readout = QLabel("Time: --      Amplitude: --")
        self.cursor_readout.setObjectName("CursorReadout")
        toolbar_layout.addWidget(self.cursor_readout)

        layout.addWidget(toolbar)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(COLOR_BACKGROUND)
        plot_item = self.plot_widget.getPlotItem()
        plot_item.showGrid(x=True, y=True, alpha=0.25)
        plot_item.setLabel("bottom", "Time (HH:MM:SS)", color=COLOR_AXIS_TEXT, **{"font-size": "10pt"})
        plot_item.setLabel("left", "Amplitude", color=COLOR_AXIS_TEXT, **{"font-size": "10pt"})
        for axis_name in ("bottom", "left"):
            axis = plot_item.getAxis(axis_name)
            axis.setTextPen(COLOR_AXIS_TEXT)
            axis.setPen("#666666")
        plot_item.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        layout.addWidget(self.plot_widget, 1)

        self._init_crosshair()

        self.year_combo.currentTextChanged.connect(self._on_year_changed)
        self.month_combo.currentTextChanged.connect(self._on_month_changed)
        self.plot_button.clicked.connect(self._on_plot)
        self.zoom_in_button.clicked.connect(self._zoom_in)
        self.zoom_out_button.clicked.connect(self._zoom_out)
        self.reset_view_button.clicked.connect(self._reset_view)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self._populate_years()

    # ------------------------------------------------------------------
    # Crosshair / cursor readout
    # ------------------------------------------------------------------
    def _init_crosshair(self):
        self._crosshair_v = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen(color="#4A4A4A", width=1, style=Qt.PenStyle.DashLine)
        )
        self._crosshair_h = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen(color="#4A4A4A", width=1, style=Qt.PenStyle.DashLine)
        )
        self._crosshair_v.hide()
        self._crosshair_h.hide()
        self.plot_widget.addItem(self._crosshair_v, ignoreBounds=True)
        self.plot_widget.addItem(self._crosshair_h, ignoreBounds=True)

    def _on_mouse_moved(self, scene_pos: QPointF):
        plot_item = self.plot_widget.getPlotItem()
        view_box = plot_item.getViewBox()
        if not self.plot_widget.sceneBoundingRect().contains(scene_pos):
            self._crosshair_v.hide()
            self._crosshair_h.hide()
            return
        if not self._timestamps:
            return

        data_pos = view_box.mapSceneToView(scene_pos)
        x_value = data_pos.x()
        index = int(round(x_value))
        if index < 0 or index >= len(self._timestamps):
            self._crosshair_v.hide()
            self._crosshair_h.hide()
            return

        self._crosshair_v.setPos(index)
        self._crosshair_h.setPos(data_pos.y())
        self._crosshair_v.show()
        self._crosshair_h.show()
        self.cursor_readout.setText(
            f"Time: {self._timestamps[index]}      Amplitude: {data_pos.y():.2f}"
        )

    # ------------------------------------------------------------------
    # Zoom controls
    # ------------------------------------------------------------------
    def _zoom_in(self):
        self.plot_widget.getViewBox().scaleBy((0.8, 0.8))

    def _zoom_out(self):
        self.plot_widget.getViewBox().scaleBy((1.25, 1.25))

    def _reset_view(self):
        self.plot_widget.getViewBox().autoRange()

    # ------------------------------------------------------------------
    # Year / Month / Day browsing
    # ------------------------------------------------------------------
    def _populate_years(self):
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        self.year_combo.addItems(self._logger.available_years())
        self.year_combo.blockSignals(False)
        self._on_year_changed(self.year_combo.currentText())

    def _on_year_changed(self, year: str):
        self.month_combo.blockSignals(True)
        self.month_combo.clear()
        if year:
            self.month_combo.addItems(self._logger.available_months(year))
        self.month_combo.blockSignals(False)
        self._on_month_changed(self.month_combo.currentText())

    def _on_month_changed(self, month: str):
        self.day_combo.blockSignals(True)
        self.day_combo.clear()
        year = self.year_combo.currentText()
        if year and month:
            self.day_combo.addItems(self._logger.available_days(year, month))
        self.day_combo.blockSignals(False)

    def _on_plot(self):
        year = self.year_combo.currentText()
        month = self.month_combo.currentText()
        day = self.day_combo.currentText()
        if not (year and month and day):
            QMessageBox.information(self, "No day selected", "Choose a Year/Month/Day first.")
            return

        path = self._logger.day_file(year, month, day)
        if path is None:
            QMessageBox.information(self, "No recording found", "No log file exists for that day.")
            return

        try:
            timestamps, freq_labels, columns, session_boundaries = AmplitudeLogger.read_day_file(path)
        except (OSError, StopIteration) as exc:
            QMessageBox.warning(self, "Could not read log file", str(exc))
            return

        self._timestamps = timestamps
        self.plot_widget.clear()
        self._init_crosshair()
        plot_item = self.plot_widget.getPlotItem()
        legend = plot_item.addLegend(offset=(10, 10))

        x_values = list(range(len(timestamps)))
        for i, (label, values) in enumerate(zip(freq_labels, columns)):
            color = TRACE_COLORS[i % len(TRACE_COLORS)]
            self.plot_widget.plot(
                x_values, values, pen=pg.mkPen(color=color, width=1.8), name=label
            )

        # Thin vertical red lines mark each session boundary within the day.
        # The very first session's boundary (row 0) is skipped -- there is
        # nothing to differentiate it from, and it would just sit on the
        # plot's left edge.
        for boundary_index in session_boundaries:
            if boundary_index == 0:
                continue
            line = pg.InfiniteLine(
                pos=boundary_index,
                angle=90,
                pen=pg.mkPen(color=COLOR_SESSION_LINE, width=1, style=Qt.PenStyle.SolidLine),
            )
            line.setZValue(-1)
            self.plot_widget.addItem(line)

        axis = plot_item.getAxis("bottom")
        tick_step = max(1, len(timestamps) // 12)
        ticks = [(i, timestamps[i]) for i in range(0, len(timestamps), tick_step)]
        axis.setTicks([ticks])

        self._reset_view()
        self.cursor_readout.setText("Time: --      Amplitude: --")
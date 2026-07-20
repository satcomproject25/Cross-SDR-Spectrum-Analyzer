"""
gui.py
------
Main application window for the Software Spectrum Analyzer.
Redesigned for Professional Laboratory-Grade Real-Time Monitoring.
Owner: Developer B (Frontend/GUI)
"""

import sys
import re
import threading
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QPoint
from PyQt6.QtGui import QKeySequence, QShortcut, QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QLabel, QComboBox, QDoubleSpinBox, QPushButton,
    QStatusBar, QSplitter, QSpinBox, QFrame, QSizePolicy,
    QDockWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMenu, QFormLayout, QGridLayout, QTabWidget
)

# --- Imported Modules (Assumes these exist in the project) ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.acquisition import create_acquisition
from backend.models import AcquisitionConfig, SpectrumFrame
from frontend.renderer import SpectrumWidget
from frontend.waterfall import WaterfallWidget
from frontend.recorder import Recorder
from frontend.freq_control import FrequencyControl
from frontend.marker_dropdown import MarkerSelectorButton


DEVICE_PROFILES = {
    "SIMULATOR": {
        "sample_rates": ("2", "5", "8", "10", "12.5", "16", "20"),
        "sample_rate": "20",
        "max_span_hz": 20e6,
        "span_hz": 20e6,
        "summary": "20 MS/s · 20 MHz span",
        "detail": "Local IQ simulator · no SDR hardware required",
    },
    "HACKRF": {
        "sample_rates": ("2", "5", "8", "10", "12.5", "16", "20"),
        "sample_rate": "20",
        "max_span_hz": 20e6,
        "span_hz": 20e6,
        "summary": "20 MS/s · 20 MHz span",
        "detail": "HackRF One supported ceiling · dedicated USB 2.0 bus recommended",
    },
    "USRP": {
        "sample_rates": ("10", "20", "25", "40", "50", "100", "200"),
        "sample_rate": "200",
        "max_span_hz": 160e6,
        "span_hz": 160e6,
        "summary": "200 MS/s · 160 MHz span",
        "detail": "X300-series maximum · requires 160 MHz daughterboard and 10 GigE/PCIe",
    },
}


# ---------------------------------------------------------------------------
# SpectrumFrame — shared contract with backend (Developer A)
# DO NOT MODIFY
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Backend bridge stub — DELETE and replace with real sdr.py backend
# ---------------------------------------------------------------------------
class BackendBridge(QObject):
    frame_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._thread = None
        self._acquisition = None
        self._pending_config = None

    def start(self, config):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._pending_config = config
                self._acquisition.stop()
                return
            acquisition = create_acquisition(config)
            self._acquisition = acquisition
            self._thread = threading.Thread(
                target=self._run, args=(acquisition,), name="sdr-acquisition", daemon=True
            )
            self._thread.start()

    def _run(self, acquisition):
        try:
            acquisition.run(self.frame_ready.emit, self.status_changed.emit)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            with self._lock:
                pending = self._pending_config
                self._pending_config = None
                self._thread = None
                self._acquisition = None
            if pending is not None:
                self.start(pending)

    def stop(self):
        with self._lock:
            self._pending_config = None
            acquisition = self._acquisition
        if acquisition is not None:
            acquisition.stop()

    def reset_min_hold(self):
        with self._lock:
            acquisition = self._acquisition
        if acquisition is not None and hasattr(acquisition, "reset_min_hold"):
            acquisition.reset_min_hold()


# ---------------------------------------------------------------------------
# Small floating Delta Marker Readout
# ---------------------------------------------------------------------------
class DeltaMarkerReadout(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(240, 160)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.title_label = QLabel("Δ Marker")
        self.title_label.setStyleSheet("""
            QLabel {
                color: #FF00FF; /* Magenta */
                font-weight: bold;
                font-size: 10pt;
                background-color: rgba(20, 20, 20, 230);
                padding: 4px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
        """)
        layout.addWidget(self.title_label)

        self.content_label = QLabel("No marker placed")
        self.content_label.setFont(QFont("Consolas", 9))
        self.content_label.setStyleSheet("""
            QLabel {
                background-color: rgba(17, 17, 17, 245);
                color: #FFFFFF;
                padding: 8px;
                border: 1px solid #3A3A3A;
                border-bottom-left-radius: 4px;
                border-bottom-right-radius: 4px;
            }
        """)
        self.content_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.content_label)

        self.setStyleSheet("background: transparent;")

    def update_delta(self, mid: int, delta_info: dict = None):
        if not delta_info:
            self.content_label.setText(f"Marker {mid} — Delta not active")
            return

        lines = [
            f"M{mid}  ↔  M{mid}Δ",
            "─────────────",
            f"Δf:  {delta_info['delta_f']/1e6:+.4f} MHz",
            f"ΔA:  {delta_info['delta_a']:+.2f} dB",
            "",
            f"Ref:   {delta_info['frequency']/1e6:.4f} MHz",
            f"Delta: {delta_info['d_frequency']/1e6:.4f} MHz",
            f"Ref:   {delta_info['amplitude']:.2f} dBFS",
            f"Delta: {delta_info['d_amplitude']:.2f} dBFS",
        ]
        self.content_label.setText("\n".join(lines))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Professional Software Spectrum Analyzer")
        self.resize(1600, 900)
        self._apply_dark_theme()

        self._is_running = False
        self._last_frame = None
        self._last_frame_time = None
        self._min_hold_was_enabled = False

        # Base Layout Initialization
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AnimatedDocks)
        
        # Build UI Components
        self._build_central_widgets()
        self._build_toolbar_ribbon()
        self._build_left_dock()
        self._build_right_dock()
        self._build_delta_readout()
        self._build_statusbar()
        self._build_panel_toggles()
        
        # Wiring and configuration
        self._wire_actions()
        self._build_shortcuts()
        self._wire_backend()
        self._setup_context_menu()

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #000000; }
            QWidget {
                color: #F2F2F2;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 10pt;
            }
            QDockWidget {
                color: #F2F2F2;
                font-weight: 600;
            }
            QDockWidget::title {
                background: #090909;
                padding: 10px 12px;
                border-bottom: 1px solid #363636;
            }
            QToolBar {
                background-color: #050505;
                border: none;
                border-bottom: 1px solid #363636;
                spacing: 10px;
                padding: 7px 12px;
            }
            QPushButton {
                background-color: #171717;
                border: 1px solid #484848;
                padding: 8px 13px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #262626; border-color: #45D9F2; }
            QPushButton:pressed { background-color: #0F0F0F; }
            QPushButton:checked {
                background-color: #0B353C;
                border-color: #33D6EE;
                color: #8DEEFF;
            }
            QPushButton:disabled {
                background-color: #0D0D0D;
                border-color: #2D2D2D;
                color: #737373;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #111111;
                border: 1px solid #484848;
                padding: 7px 9px;
                border-radius: 6px;
                selection-background-color: #0B5664;
            }
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #45D9F2; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background-color: #101010;
                color: #F2F2F2;
                border: 1px solid #484848;
                selection-background-color: #0B5664;
                selection-color: #FFFFFF;
            }
            QGroupBox {
                background-color: #0A0A0A;
                border: 1px solid #363636;
                border-radius: 9px;
                margin-top: 13px;
                padding: 12px 8px 8px 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #BFC7D0;
                font-weight: 600;
            }
            QTabWidget::pane { border: none; background: #000000; }
            QTabBar::tab {
                background: #090909;
                color: #B8B8B8;
                border-bottom: 2px solid transparent;
                padding: 10px 14px;
                min-width: 72px;
            }
            QTabBar::tab:selected { color: #8DEEFF; border-bottom-color: #33D6EE; }
            QTabBar::tab:hover { color: #FFFFFF; background: #151515; }
            QTableWidget {
                background-color: #080808;
                alternate-background-color: #141414;
                gridline-color: #383838;
                border: 1px solid #383838;
                border-radius: 7px;
            }
            QHeaderView::section {
                background-color: #181818;
                color: #D8D8D8;
                padding: 7px;
                border: none;
                border-right: 1px solid #383838;
            }
            QStatusBar { background: #050505; border-top: 1px solid #363636; }
            QStatusBar QLabel { color: #C8C8C8; padding: 2px 5px; }
            QLabel#BrandTitle { color: #FFFFFF; font-size: 15pt; font-weight: 700; }
            QLabel#BrandSubtitle { color: #A8A8A8; font-size: 8.5pt; }
            QLabel#SectionLabel { color: #B8B8B8; font-size: 8pt; font-weight: 700; }
            QLabel#ProfileBadge {
                background: #09272C;
                color: #8DEEFF;
                border: 1px solid #287586;
                border-radius: 6px;
                padding: 7px 10px;
            }
            QLabel#ProfileDetail {
                background: #081C1F;
                color: #B6E6EE;
                border: 1px solid #28545C;
                border-radius: 7px;
                padding: 9px;
            }
            QLabel#MetricValue { color: #FFFFFF; font-weight: 700; }
            QPushButton#RunButton {
                background: #0F4C3A;
                border-color: #1B7A5C;
                color: #8FF0C7;
                padding-left: 18px;
                padding-right: 18px;
            }
            QPushButton#RunButton:checked {
                background: #4A3512;
                border-color: #A66D18;
                color: #FFD38A;
            }
            QPushButton#PanelToggle {
                background: #161616;
                color: #8DEEFF;
                border: 1px solid #287586;
                border-radius: 5px;
                padding: 0px;
                font-size: 17pt;
                font-weight: 700;
            }
            QPushButton#PanelToggle:hover {
                background: #0B353C;
                border-color: #33D6EE;
            }
            QToolTip {
                background-color: #161616;
                color: #FFFFFF;
                border: 1px solid #585858;
                padding: 4px;
            }
        """)

    # -----------------------------------------------------------------------
    # Central Layout
    # -----------------------------------------------------------------------
    def _build_central_widgets(self):
        self.spectrum_widget  = SpectrumWidget()
        self.waterfall_widget = WaterfallWidget()
        self.waterfall_widget.link_frequency_axis(
            self.spectrum_widget.plot_widget
        )

        center_split = QSplitter(Qt.Orientation.Vertical)
        center_split.addWidget(self.spectrum_widget)
        center_split.addWidget(self.waterfall_widget)
        
        # 70% Spectrum, 30% Waterfall allocation
        center_split.setStretchFactor(0, 7)
        center_split.setStretchFactor(1, 3)
        center_split.setHandleWidth(3)
        center_split.setSizes([620, 280])

        self.setCentralWidget(center_split)

    def _build_delta_readout(self):
        self.delta_readout = DeltaMarkerReadout(self)
        self.delta_readout.hide()

    # -----------------------------------------------------------------------
    # Top Control Ribbon
    # -----------------------------------------------------------------------
    def _build_toolbar_ribbon(self):
        self._toolbar = QToolBar("Analyzer Header")
        self._toolbar.setMovable(False)
        self._toolbar.setFixedHeight(72)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 20, 0)
        brand_layout.setSpacing(0)
        brand_title = QLabel("FREQUENCY ANALYZER")
        brand_title.setObjectName("BrandTitle")
        brand_subtitle = QLabel("REAL-TIME RF SPECTRUM WORKBENCH")
        brand_subtitle.setObjectName("BrandSubtitle")
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_subtitle)
        self._toolbar.addWidget(brand)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toolbar.addWidget(spacer)

        device_block = QWidget()
        device_layout = QVBoxLayout(device_block)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(2)
        device_label = QLabel("INPUT DEVICE")
        device_label.setObjectName("SectionLabel")
        self.sdr_type_combo = QComboBox()
        self.sdr_type_combo.setMinimumWidth(190)
        self.sdr_type_combo.addItem("Simulator", "SIMULATOR")
        self.sdr_type_combo.addItem("HackRF One", "HACKRF")
        self.sdr_type_combo.addItem("Ettus USRP X301", "USRP")
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.sdr_type_combo)
        self._toolbar.addWidget(device_block)

        self.lbl_profile_badge = QLabel()
        self.lbl_profile_badge.setObjectName("ProfileBadge")
        self.lbl_profile_badge.setMinimumWidth(185)
        self._toolbar.addWidget(self.lbl_profile_badge)

        self.btn_run_stop = QPushButton("Start acquisition")
        self.btn_run_stop.setObjectName("RunButton")
        self.btn_run_stop.setCheckable(True)
        self._toolbar.addWidget(self.btn_run_stop)

    # -----------------------------------------------------------------------
    # Left Dock Panel
    # -----------------------------------------------------------------------
    def _build_left_dock(self):
        self.left_dock = QDockWidget("Analyzer Setup", self)
        self.left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.left_dock.setMinimumWidth(280)
        self.left_dock.setMaximumWidth(330)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Frequency Group
        grp_freq = QGroupBox("Tuning")
        lyt_freq = QFormLayout(grp_freq)
        self.center_freq_ctrl = FrequencyControl(initial_hz=2440e6, minimum_hz=1e6, maximum_hz=6e9, default_unit="MHz")
        self.span_ctrl = FrequencyControl(initial_hz=20e6, minimum_hz=1e5, maximum_hz=20e6, default_unit="MHz")
        lyt_freq.addRow("Center:", self.center_freq_ctrl)
        lyt_freq.addRow("Span:", self.span_ctrl)
        layout.addWidget(grp_freq)

        # Receiver Group
        grp_rx = QGroupBox("Receiver")
        lyt_rx = QFormLayout(grp_rx)
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["2", "5", "8", "10", "12.5", "16", "20"])
        self.sample_rate_combo.setCurrentText("20")
        
        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(0, 62)
        self.gain_spin.setValue(20)
        
        self.reference_level_spin = QDoubleSpinBox()
        self.reference_level_spin.setRange(-150, 50)
        self.reference_level_spin.setValue(0)
        self.reference_level_spin.setSuffix(" dBFS")

        lyt_rx.addRow("Reference:", self.reference_level_spin)
        lyt_rx.addRow("SR (Msps):", self.sample_rate_combo)
        lyt_rx.addRow("Gain (dB):", self.gain_spin)
        layout.addWidget(grp_rx)

        self.lbl_profile_detail = QLabel()
        self.lbl_profile_detail.setObjectName("ProfileDetail")
        self.lbl_profile_detail.setWordWrap(True)
        layout.addWidget(self.lbl_profile_detail)

        self.left_dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

    # -----------------------------------------------------------------------
    # Right Dock Panel (Analytics & Tables)
    # -----------------------------------------------------------------------
    def _build_right_dock(self):
        self.right_dock = QDockWidget("Analysis", self)
        self.right_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.right_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.right_dock.setMinimumWidth(360)
        self.right_dock.setMaximumWidth(410)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.tabBar().setExpanding(True)
        tabs.tabBar().setUsesScrollButtons(False)

        # Measurements tab
        measurements_tab = QWidget()
        measurements_layout = QVBoxLayout(measurements_tab)
        measurements_layout.setContentsMargins(12, 12, 12, 12)
        measurements_layout.setSpacing(12)
        grp_meas = QGroupBox("Live Measurements")
        lyt_meas = QFormLayout(grp_meas)
        lyt_meas.setVerticalSpacing(12)
        self.lbl_meas_peak_freq = QLabel("-- MHz")
        self.lbl_meas_peak_amp  = QLabel("-- dBFS")
        self.lbl_meas_noise     = QLabel("-- dBFS")
        self.lbl_meas_obw       = QLabel("-- kHz")
        self.lbl_meas_chan_pwr  = QLabel("-- dBFS")
        for label in (
            self.lbl_meas_peak_freq,
            self.lbl_meas_peak_amp,
            self.lbl_meas_noise,
            self.lbl_meas_obw,
            self.lbl_meas_chan_pwr,
        ):
            label.setObjectName("MetricValue")

        lyt_meas.addRow("Peak Freq:", self.lbl_meas_peak_freq)
        lyt_meas.addRow("Peak Amp:", self.lbl_meas_peak_amp)
        lyt_meas.addRow("Noise Floor:", self.lbl_meas_noise)
        lyt_meas.addRow("Occ Bandwidth:", self.lbl_meas_obw)
        lyt_meas.addRow("Channel Power:", self.lbl_meas_chan_pwr)
        measurements_layout.addWidget(grp_meas)

        grp_export = QGroupBox("Capture & Export")
        export_layout = QHBoxLayout(grp_export)
        self.btn_screenshot = QPushButton("Screenshot")
        self.btn_export_csv = QPushButton("Export CSV")
        export_layout.addWidget(self.btn_screenshot)
        export_layout.addWidget(self.btn_export_csv)
        measurements_layout.addWidget(grp_export)
        measurements_layout.addStretch(1)

        # Traces tab
        traces_tab = QWidget()
        traces_layout = QVBoxLayout(traces_tab)
        traces_layout.setContentsMargins(12, 12, 12, 12)
        traces_layout.setSpacing(12)
        grp_trace_controls = QGroupBox("Visible Traces")
        trace_grid = QGridLayout(grp_trace_controls)
        self.btn_clear_write = QPushButton("CW · Clear Write")
        self.btn_max_hold = QPushButton("Max Hold")
        self.btn_min_hold = QPushButton("Min Hold")
        self.btn_average = QPushButton("Average")
        self.btn_carriers = QPushButton("Carrier")
        self.btn_carriers.setCheckable(True)
        self.btn_carriers.setChecked(True)
        for btn in (
            self.btn_clear_write,
            self.btn_max_hold,
            self.btn_min_hold,
            self.btn_average,
        ):
            btn.setCheckable(True)
            btn.setMinimumHeight(42)
        self.btn_clear_write.setChecked(True)
        trace_grid.addWidget(self.btn_clear_write, 0, 0)
        trace_grid.addWidget(self.btn_max_hold, 0, 1)

        trace_grid.addWidget(self.btn_min_hold, 1, 0)
        trace_grid.addWidget(self.btn_average, 1, 1)

        trace_grid.addWidget(self.btn_carriers, 2, 0, 1, 2)
        traces_layout.addWidget(grp_trace_controls)

        grp_traces = QGroupBox("Active Traces")
        lyt_traces = QVBoxLayout(grp_traces)
        self.lbl_trace_status = QLabel("Clear Write: ON\nMax Hold: OFF\nMin Hold: OFF\nAverage: OFF")
        self.lbl_trace_status.setFont(QFont("Consolas", 9))
        lyt_traces.addWidget(self.lbl_trace_status)
        traces_layout.addWidget(grp_traces)
        traces_layout.addStretch(1)

        # Markers tab
        markers_tab = QWidget()
        markers_layout = QVBoxLayout(markers_tab)
        markers_layout.setContentsMargins(12, 12, 12, 12)
        markers_layout.setSpacing(12)

        grp_marker_controls = QGroupBox("Marker Control")
        marker_form = QFormLayout(grp_marker_controls)
        self.marker_selector_btn = MarkerSelectorButton()
        self.trace_marker_combo = QComboBox()
        self.trace_marker_combo.addItem("CW", "cw")
        self.trace_marker_combo.addItem("Max hold", "max_hold")
        self.trace_marker_combo.addItem("Min hold", "min_hold")
        self.trace_marker_combo.addItem("Average", "average")
        marker_form.addRow("Active marker:", self.marker_selector_btn)
        marker_form.addRow("Trace marker:", self.trace_marker_combo)

        marker_actions = QHBoxLayout()
        self.btn_delta_marker = QPushButton("Δ Delta")
        self.btn_delta_marker.setCheckable(True)
        self.btn_delta_marker.setEnabled(False)
        self.btn_clear_markers = QPushButton("Clear All")
        marker_actions.addWidget(self.btn_delta_marker)
        marker_actions.addWidget(self.btn_clear_markers)
        marker_form.addRow(marker_actions)
        markers_layout.addWidget(grp_marker_controls)

        self.grp_mkrs = QGroupBox("Marker Table — CW")
        lyt_mkrs = QVBoxLayout(self.grp_mkrs)
        self.table_markers = QTableWidget(0, 4)
        self.table_markers.setMinimumHeight(280)
        self.table_markers.setHorizontalHeaderLabels(["ID", "Freq", "Amp", "Delta"])
        self.table_markers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_markers.setAlternatingRowColors(True)
        self.table_markers.verticalHeader().setVisible(False)
        self.table_markers.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.EditKeyPressed
        )
        lyt_mkrs.addWidget(self.table_markers)
        markers_layout.addWidget(self.grp_mkrs, 1)

        tabs.addTab(measurements_tab, "Measure")
        tabs.addTab(traces_tab, "Traces")
        tabs.addTab(markers_tab, "Markers")
        self.analysis_tabs = tabs
        self.right_dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)

    def _build_panel_toggles(self):
        self.btn_left_panel_toggle = QPushButton("‹", self)
        self.btn_right_panel_toggle = QPushButton("›", self)
        for button in (self.btn_left_panel_toggle, self.btn_right_panel_toggle):
            button.setObjectName("PanelToggle")
            button.setFixedSize(26, 58)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.btn_left_panel_toggle.setAccessibleName("Toggle Analyzer Setup panel")
        self.btn_right_panel_toggle.setAccessibleName("Toggle Analysis panel")
        self.btn_left_panel_toggle.clicked.connect(self._toggle_left_panel)
        self.btn_right_panel_toggle.clicked.connect(self._toggle_right_panel)
        self.left_dock.visibilityChanged.connect(self._sync_panel_toggles)
        self.right_dock.visibilityChanged.connect(self._sync_panel_toggles)
        self._sync_panel_toggles()

    def _toggle_left_panel(self):
        if self.left_dock.isVisible():
            self.left_dock.hide()
        else:
            if self.left_dock.isFloating():
                self.left_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)
            self.left_dock.show()
            self.left_dock.raise_()
        self._sync_panel_toggles()

    def _toggle_right_panel(self):
        if self.right_dock.isVisible():
            self.right_dock.hide()
        else:
            if self.right_dock.isFloating():
                self.right_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)
            self.right_dock.show()
            self.right_dock.raise_()
        self._sync_panel_toggles()

    def _sync_panel_toggles(self, *_):
        left_open = self.left_dock.isVisible()
        right_open = self.right_dock.isVisible()
        self.btn_left_panel_toggle.setText("‹" if left_open else "›")
        self.btn_right_panel_toggle.setText("›" if right_open else "‹")
        self.btn_left_panel_toggle.setToolTip(
            "Hide Analyzer Setup" if left_open else "Show Analyzer Setup"
        )
        self.btn_right_panel_toggle.setToolTip(
            "Hide Analysis" if right_open else "Show Analysis"
        )
        self._position_panel_toggles()

    def _position_panel_toggles(self):
        if not hasattr(self, "btn_left_panel_toggle"):
            return
        central = self.centralWidget().geometry()
        handle_height = self.btn_left_panel_toggle.height()
        y = central.top() + max(8, (central.height() - handle_height) // 2)

        if self.left_dock.isVisible() and not self.left_dock.isFloating():
            left_x = self.left_dock.geometry().right() + 1
        else:
            left_x = 0

        if self.right_dock.isVisible() and not self.right_dock.isFloating():
            right_x = self.right_dock.geometry().left() - self.btn_right_panel_toggle.width()
        else:
            right_x = self.width() - self.btn_right_panel_toggle.width()

        self.btn_left_panel_toggle.move(max(0, left_x), y)
        self.btn_right_panel_toggle.move(
            min(self.width() - self.btn_right_panel_toggle.width(), right_x), y
        )
        self.btn_left_panel_toggle.raise_()
        self.btn_right_panel_toggle.raise_()

    # -----------------------------------------------------------------------
    # Status Bar
    # -----------------------------------------------------------------------
    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_device_status = QLabel("Device: Disconnected")
        self.lbl_fft_size = QLabel("FFT Size: 2048")
        self.lbl_rbw = QLabel("RBW: 9.7 kHz")
        self.lbl_fps = QLabel("FPS: --")
        self.lbl_peak_status = QLabel("Peak: -- dBFS")

        self.status_bar.addWidget(self.lbl_device_status)
        self.status_bar.addWidget(QLabel(" | "))
        self.status_bar.addWidget(self.lbl_fft_size)
        self.status_bar.addWidget(QLabel(" | "))
        self.status_bar.addWidget(self.lbl_rbw)
        
        self.status_bar.addPermanentWidget(self.lbl_peak_status)
        self.status_bar.addPermanentWidget(self.lbl_fps)

    # -----------------------------------------------------------------------
    # Wiring & Event Handlers
    # -----------------------------------------------------------------------
    def _wire_actions(self):
        self.recorder = Recorder(self)
        
        # Toolbar actions
        self.btn_run_stop.clicked.connect(self._toggle_run)
        
        self.btn_clear_write.clicked.connect(self._update_trace_modes)
        self.btn_max_hold.clicked.connect(self._update_trace_modes)
        self.btn_min_hold.clicked.connect(self._update_trace_modes)
        self.btn_average.clicked.connect(self._update_trace_modes)
        self.btn_carriers.toggled.connect(
                self._toggle_carrier_detection
            )
        
        self.btn_screenshot.clicked.connect(lambda: self.recorder.take_screenshot())
        self.btn_export_csv.clicked.connect(lambda: self.recorder.export_csv(self._last_frame))

        # Marker actions
        self.spectrum_widget.markers_changed.connect(self._on_markers_changed)
        self.marker_selector_btn.marker_selected.connect(self._on_marker_selected)
        self.btn_delta_marker.clicked.connect(self._on_delta_toggle)
        self.btn_clear_markers.clicked.connect(self._on_clear_markers)
        self.table_markers.itemChanged.connect(self._on_marker_table_changed)
        self.trace_marker_combo.currentIndexChanged.connect(
            self._on_trace_marker_changed
        )

        self.center_freq_ctrl.value_changed_hz.connect(self._configuration_changed)
        self.span_ctrl.value_changed_hz.connect(self._configuration_changed)
        self.sample_rate_combo.currentTextChanged.connect(self._sample_rate_changed)
        self.gain_spin.valueChanged.connect(self._configuration_changed)
        self.sdr_type_combo.currentTextChanged.connect(self._device_type_changed)   # was _configuration_changed
        self.reference_level_spin.valueChanged.connect(
         self._reference_level_changed
        )
        self._apply_device_profile()

    def _update_trace_modes(self):
        cw = self.btn_clear_write.isChecked()
        mh = self.btn_max_hold.isChecked()
        mi = self.btn_min_hold.isChecked()
        av = self.btn_average.isChecked()
        
        self.spectrum_widget.set_trace_mode(clear_write=cw)
        self.spectrum_widget.set_trace_mode(max_hold=mh)
        self.spectrum_widget.set_trace_mode(min_hold=mi)
        self.spectrum_widget.set_trace_mode(average=av)

        if mi and not self._min_hold_was_enabled:
            self.backend.reset_min_hold()
        self._min_hold_was_enabled = mi

        status_text = (f"Clear Write: {'ON' if cw else 'OFF'}\n"
                       f"Max Hold: {'ON' if mh else 'OFF'}\n"
                       f"Min Hold: {'ON' if mi else 'OFF'}\n"
                       f"Average: {'ON' if av else 'OFF'}")
        self.lbl_trace_status.setText(status_text)

    def _toggle_carrier_detection(self, checked):

        self.spectrum_widget.set_carrier_visibility(checked)

        self.status_bar.showMessage(
            f"Carrier Detection {'Enabled' if checked else 'Disabled'}",
            2500
        )
        
    def _on_trace_marker_changed(self, _index=None):
        trace_name = self.trace_marker_combo.currentData()
        trace_button = {
            "cw": self.btn_clear_write,
            "max_hold": self.btn_max_hold,
            "min_hold": self.btn_min_hold,
            "average": self.btn_average,
        }[trace_name]
        if not trace_button.isChecked():
            trace_button.setChecked(True)
            self._update_trace_modes()
        self.spectrum_widget.set_marker_trace(trace_name)
        label = self.trace_marker_combo.currentText()
        self.grp_mkrs.setTitle(f"Marker Table — {label}")
        self.status_bar.showMessage(f"Markers attached to {label} trace", 2500)

    def _on_marker_selected(self, marker_id: int):
        self.spectrum_widget.set_active_marker(marker_id)
        self.btn_delta_marker.setEnabled(marker_id != 0)
        self.btn_delta_marker.blockSignals(True)
        try:
            self.btn_delta_marker.setChecked(
                marker_id in self.spectrum_widget._delta_markers
            )
        finally:
            self.btn_delta_marker.blockSignals(False)
        self._refresh_readout_for_current_marker(marker_id)

    def _build_shortcuts(self):
        shortcut_map = {
            "Space":  self._toggle_run,
            "C":      lambda: self.btn_clear_write.click(),
            "Ctrl+H": lambda: self.btn_max_hold.click(),
            "Ctrl+L": lambda: self.btn_min_hold.click(),
            "Ctrl+G": lambda: self.btn_average.click(),
            "Shift+M":lambda: self.btn_delta_marker.click(),
            "S":      lambda: self.btn_screenshot.click(),
            "Ctrl+E": lambda: self.btn_export_csv.click(),
            "+":      self.spectrum_widget.zoom_in,
            "-":      self.spectrum_widget.zoom_out,
            "R":      self.spectrum_widget.reset_zoom,
            "Escape": self._stop_acquisition,
        }
        self._shortcuts = []
        for key_seq, handler in shortcut_map.items():
            sc = QShortcut(QKeySequence(key_seq), self)
            sc.activated.connect(handler)
            self._shortcuts.append(sc)

    def _setup_context_menu(self):
        self.spectrum_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.spectrum_widget.customContextMenuRequested.connect(self._show_spectrum_context_menu)

    def _show_spectrum_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #101010; color: #F2F2F2; "
            "border: 1px solid #484848; padding: 5px; } "
            "QMenu::item { padding: 7px 24px; border-radius: 4px; } "
            "QMenu::item:selected { background-color: #0B353C; color: #8DEEFF; } "
            "QMenu::item:disabled { color: #737373; }"
        )
        
        action_add_marker = QAction("Add Marker", self)
        action_del_marker = QAction("Clear Markers", self)
        action_center = QAction("Center Here", self)
        action_peak = QAction("Peak Search", self)
        marker_enabled = self.marker_selector_btn.current_marker_id() != 0
        action_add_marker.setEnabled(marker_enabled)
        action_peak.setEnabled(marker_enabled)
        
        menu.addAction(action_add_marker)
        menu.addAction(action_del_marker)
        menu.addSeparator()
        menu.addAction(action_center)
        menu.addAction(action_peak)
        menu.addSeparator()
        
        action_zoom_in = QAction("Zoom In (+)", self)
        action_zoom_in.triggered.connect(self.spectrum_widget.zoom_in)
        action_zoom_out = QAction("Zoom Out (-)", self)
        action_zoom_out.triggered.connect(self.spectrum_widget.zoom_out)
        action_reset_zoom = QAction("Reset Zoom (R)", self)
        action_reset_zoom.triggered.connect(self.spectrum_widget.reset_zoom)
        
        menu.addAction(action_zoom_in)
        menu.addAction(action_zoom_out)
        menu.addAction(action_reset_zoom)
        menu.addSeparator()
        
        action_screenshot = QAction("Screenshot", self)
        action_screenshot.triggered.connect(lambda: self.recorder.take_screenshot())
        menu.addAction(action_screenshot)

        selected_frequency = self.spectrum_widget.frequency_at_widget_position(pos)
        action_add_marker.triggered.connect(
            lambda: self.spectrum_widget.place_active_marker_at_frequency(selected_frequency)
            if selected_frequency is not None else None
        )
        action_del_marker.triggered.connect(self._on_clear_markers)
        action_center.triggered.connect(
            lambda: self._center_on_frequency(selected_frequency)
            if selected_frequency is not None else None
        )
        action_peak.triggered.connect(self.spectrum_widget.place_active_marker_at_peak)

        menu.exec(self.spectrum_widget.mapToGlobal(pos))

    def _center_on_frequency(self, frequency):
        self.center_freq_ctrl.set_value_hz(frequency)
        self._configuration_changed()

    # -----------------------------------------------------------------------
    # Backend Wiring & Frame Updates
    # -----------------------------------------------------------------------
    def _wire_backend(self):
        self.backend = BackendBridge()
        self.backend.frame_ready.connect(self._on_frame_ready)
        self.backend.status_changed.connect(self._on_backend_status)
        self.backend.error.connect(self._on_backend_error)

    def _acquisition_config(self):
        return AcquisitionConfig(
            device_type=self.sdr_type_combo.currentData(),
            center_frequency=self.center_freq_ctrl.value_hz(),
            sample_rate=float(self.sample_rate_combo.currentText()) * 1e6,
            span=self.span_ctrl.value_hz(),
            gain=float(self.gain_spin.value()),
            fft_size=4096,
        )

    def _configuration_changed(self, *_):
        if self._is_running:
            self.lbl_device_status.setText("Device: Reconfiguring...")
            self.backend.start(self._acquisition_config())

    def _sample_rate_changed(self, sample_rate_text: str):
        if not sample_rate_text:
            return
        profile = DEVICE_PROFILES[self.sdr_type_combo.currentData()]
        maximum_span = min(
            profile["max_span_hz"], float(sample_rate_text) * 1e6
        )
        self.span_ctrl.set_limits_hz(1e5, maximum_span)
        self._configuration_changed()

    def _device_type_changed(self, *_):
        if self._is_running:
            self._stop_acquisition()
        self._apply_device_profile()
        self.lbl_device_status.setText(
            f"Device: {self.sdr_type_combo.currentText()} selected - press Run"
        )

    def _apply_device_profile(self):
        device_type = self.sdr_type_combo.currentData()
        profile = DEVICE_PROFILES[device_type]

        self.sample_rate_combo.blockSignals(True)
        try:
            self.sample_rate_combo.clear()
            self.sample_rate_combo.addItems(profile["sample_rates"])
            self.sample_rate_combo.setCurrentText(profile["sample_rate"])
        finally:
            self.sample_rate_combo.blockSignals(False)

        self.span_ctrl.set_limits_hz(1e5, profile["max_span_hz"])
        self.span_ctrl.set_suffix_visible_unit("MHz")
        self.span_ctrl.set_value_hz(profile["span_hz"])
        self.lbl_profile_badge.setText(profile["summary"])
        self.lbl_profile_detail.setText(profile["detail"])
        self.lbl_profile_badge.setToolTip(profile["detail"])

    def _toggle_run(self):
        if self._is_running:
            self._stop_acquisition()
        else:
            self._start_acquisition()

    def _start_acquisition(self):
        self._is_running = True
        self.btn_run_stop.setChecked(True)
        self.btn_run_stop.setText("Stop acquisition")
        self.lbl_device_status.setText("Device: Connecting...")
        self.backend.start(self._acquisition_config())

    def _stop_acquisition(self):
        self._is_running = False
        self.btn_run_stop.setChecked(False)
        self.btn_run_stop.setText("Start acquisition")
        self.lbl_device_status.setText("Device: Idle")
        self.backend.stop()

    def _on_backend_status(self, status: str):
        if self._is_running or status != "Idle":
            self.lbl_device_status.setText(f"Device: {status}")

    def _on_backend_error(self, message: str):
        print(f"[ACQ ERROR] {message}", flush=True)
        self.backend.stop()                      # kill any pending restart
        self.status_bar.showMessage(message, 15000)
        self.lbl_device_status.setText(f"Device error: {message}")
        self._is_running = False
        self.btn_run_stop.setChecked(False)
        self.btn_run_stop.setText("Start acquisition")

    def _on_frame_ready(self, frame: SpectrumFrame):
        self._last_frame = frame
        self.spectrum_widget.update_frame(frame)
        self.waterfall_widget.update_frame(frame)

        peak = frame.peaks[0] if frame.peaks else None
        if peak is not None:
            peak_frequency = peak.frequency
            peak_amplitude = peak.amplitude
        else:
            index = int(np.argmax(frame.amplitude))
            peak_frequency = frame.frequency[index]
            peak_amplitude = frame.amplitude[index]
        self.lbl_peak_status.setText(f"Peak: {peak_amplitude:.2f} dBFS")
        self.lbl_meas_peak_freq.setText(f"{peak_frequency/1e6:.6f} MHz")
        self.lbl_meas_peak_amp.setText(f"{peak_amplitude:.2f} dBFS")
        self.lbl_meas_noise.setText(f"{frame.noise_floor:.2f} dBFS")
        self.lbl_meas_obw.setText(f"{frame.bandwidth/1e3:.3f} kHz")
        self.lbl_meas_chan_pwr.setText(f"{frame.channel_power:.2f} dBFS")
        self.lbl_fft_size.setText(f"FFT Size: {frame.fft_size}")
        self.lbl_rbw.setText(f"RBW: {frame.rbw/1e3:.3f} kHz")
        now = time.monotonic()  
        if self._last_frame_time is not None and now > self._last_frame_time:
            self.lbl_fps.setText(f"FPS: {1.0/(now-self._last_frame_time):.1f}")
        self._last_frame_time = now
    # -----------------------------------------------------------------------
    # Marker & Delta Logic
    # -----------------------------------------------------------------------
    def _on_delta_toggle(self, checked: bool):
        mid = self.marker_selector_btn.current_marker_id()
        if checked:
            if mid not in self.spectrum_widget._markers:
                self.btn_delta_marker.setChecked(False)
                self.delta_readout.hide()
                return
            self.spectrum_widget.add_delta_marker(mid)
            self.delta_readout.show()
        else:
            self.spectrum_widget.remove_delta_marker(mid)
            self.delta_readout.hide()

    def _on_clear_markers(self):
        self.spectrum_widget.clear_markers()
        self.btn_delta_marker.setChecked(False)
        self.delta_readout.hide()
        self.table_markers.setRowCount(0)

    def _on_marker_table_changed(self, item: QTableWidgetItem):
        """Apply an edited marker frequency, accepting Hz/kHz/MHz/GHz."""
        if item.column() != 1:
            return
        row = item.row()
        id_item = self.table_markers.item(row, 0)
        if id_item is None:
            return
        try:
            marker_id = int(id_item.text().lstrip("M"))
            match = re.fullmatch(
                r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
                r"(Hz|kHz|MHz|GHz)?\s*",
                item.text(),
                re.IGNORECASE,
            )
            if match is None:
                raise ValueError("Use a number with an optional Hz, kHz, MHz, or GHz suffix")
            value = float(match.group(1))
            multiplier = {
                "hz": 1.0,
                "khz": 1e3,
                "mhz": 1e6,
                "ghz": 1e9,
            }.get((match.group(2) or "MHz").lower(), 1e6)
            frequency_hz = value * multiplier
            if not self.spectrum_widget.set_marker_frequency(marker_id, frequency_hz):
                raise ValueError("The marker is not attached to a live waveform")
        except (TypeError, ValueError) as exc:
            self.status_bar.showMessage(f"Invalid marker frequency: {exc}", 5000)
            self._update_marker_table(self._get_marker_state())

    def _on_markers_changed(self, state: dict):
        self._update_marker_table(state)
        mid = self.marker_selector_btn.current_marker_id()
        self._render_delta_readout(mid, state)

    def _refresh_readout_for_current_marker(self, mid: int):
        state = self._get_marker_state()
        self._render_delta_readout(mid, state)

    def _render_delta_readout(self, mid: int, state: dict):
        if mid not in state or not self.btn_delta_marker.isChecked():
            self.delta_readout.hide()
            return

        entry = state[mid]
        delta = entry.get("delta")
        
        if delta:
            delta_info = {
                "frequency": entry["frequency"],
                "amplitude": entry["amplitude"],
                "d_frequency": delta["frequency"],
                "d_amplitude": delta["amplitude"],
                "delta_f": delta["delta_f"],
                "delta_a": delta["delta_a"],
            }
            self.delta_readout.update_delta(mid, delta_info)
        else:
            self.delta_readout.update_delta(mid)

    def _get_marker_state(self) -> dict:
        state = {}
        for mid, target in self.spectrum_widget._markers.items():
            pos = target.pos()
            delta_info = None
            if mid in self.spectrum_widget._delta_markers:
                d_pos = self.spectrum_widget._delta_markers[mid].pos()
                delta_info = {
                    "frequency": d_pos.x(),
                    "amplitude": d_pos.y(),
                    "delta_f":   d_pos.x() - pos.x(),
                    "delta_a":   d_pos.y() - pos.y(),
                }
            state[mid] = {
                "frequency": pos.x(),
                "amplitude": pos.y(),
                "delta": delta_info,
            }
        return state

    def _update_marker_table(self, state: dict):
        self.table_markers.blockSignals(True)
        try:
            self.table_markers.setRowCount(len(state))
            for row, (mid, entry) in enumerate(state.items()):
                freq_str = f"{entry['frequency']/1e6:.4f} MHz"
                amp_str = f"{entry['amplitude']:.2f} dBFS"

                delta_str = "--"
                if entry.get("delta"):
                    delta_f = entry["delta"]["delta_f"] / 1e6
                    delta_str = f"{delta_f:+.4f} MHz"

                id_item = QTableWidgetItem(f"M{mid}")
                id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                freq_item = QTableWidgetItem(freq_str)
                amp_item = QTableWidgetItem(amp_str)
                delta_item = QTableWidgetItem(delta_str)
                for read_only_item in (amp_item, delta_item):
                    read_only_item.setFlags(
                        read_only_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )
                self.table_markers.setItem(row, 0, id_item)
                self.table_markers.setItem(row, 1, freq_item)
                self.table_markers.setItem(row, 2, amp_item)
                self.table_markers.setItem(row, 3, delta_item)
        finally:
            self.table_markers.blockSignals(False)

    def _reference_level_changed(self):
        self.spectrum_widget.set_reference_level(
            self.reference_level_spin.value(),
            120
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_panel_toggles()
        # Keep delta window floating properly
        if hasattr(self, 'delta_readout') and self.delta_readout.isVisible():
            self.delta_readout.move(self.width() - self.delta_readout.width() - 320, 100)

    def closeEvent(self, event):
        self.backend.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    
    # Custom stylesheet loading preserved (fallback to internal theme if missing)
    try:
        with open("assets/style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass # The GUI establishes its own dark theme inside _apply_dark_theme()

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

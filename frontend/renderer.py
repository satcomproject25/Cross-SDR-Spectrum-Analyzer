"""
renderer.py
-----------
Spectrum plot widget for the Software Spectrum Analyzer.
Owner: Developer B (Frontend/GUI)
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout

# ----------------------------------------------------------------------------
# Theme constants
# ----------------------------------------------------------------------------
COLOR_BACKGROUND  = "#000000"
COLOR_CLEAR_WRITE = "#00F0FF"
COLOR_MAX_HOLD    = "#FF3B30"
COLOR_MIN_HOLD    = "#3399FF"
COLOR_AVERAGE     = "#FFD60A"
COLOR_AXIS_TEXT   = "#CCCCCC"
TRACE_WIDTH = 1.6

# One color per marker slot (1, 2, 3). Delta marker reuses same color as parent.
MARKER_COLORS = {
    1: "#FFFFFF",   # white
    2: "#00FF7F",   # spring green
    3: "#FF7F00",   # orange
}

DELTA_SYMBOL = "\u0394"   # Δ


class SpectrumWidget(QWidget):
    """
    Emits markers_changed(dict) on every marker/delta-marker move.

    Payload structure:
    {
        1: {"frequency": float, "amplitude": float,
            "delta": {"frequency": float, "amplitude": float} | None},
        2: {...},
        3: {...},
    }
    Only marker IDs that have been placed are present in the dict.
    """
    markers_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_plot()
        self._init_traces()
        self._init_markers()

        self.show_clear_write = True
        self.show_max_hold    = False
        self.show_min_hold    = False
        self.show_average     = False

    # ------------------------------------------------------------------
    # Plot setup
    # ------------------------------------------------------------------
    def _build_plot(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(COLOR_BACKGROUND)

        pi = self.plot_widget.getPlotItem()
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.setLabel("bottom", "Frequency", units="Hz",
                    **{"color": COLOR_AXIS_TEXT, "font-size": "10pt"})
        pi.setLabel("left", "Amplitude", units="dBFS",
                    **{"color": COLOR_AXIS_TEXT, "font-size": "10pt"})
        self.plot_widget.setYRange(-120, 0)

        # Drag-to-zoom: left-click-drag draws a box, release zooms in
        pi.getViewBox().setMouseMode(pg.ViewBox.RectMode)

        layout.addWidget(self.plot_widget)

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------
    def _init_traces(self):
        self.curve_clear_write = self.plot_widget.plot(
            pen=pg.mkPen(color=COLOR_CLEAR_WRITE, width=TRACE_WIDTH))
        self.curve_max_hold = self.plot_widget.plot(
            pen=pg.mkPen(color=COLOR_MAX_HOLD, width=TRACE_WIDTH))
        self.curve_min_hold = self.plot_widget.plot(
            pen=pg.mkPen(color=COLOR_MIN_HOLD, width=TRACE_WIDTH))
        self.curve_average = self.plot_widget.plot(
            pen=pg.mkPen(color=COLOR_AVERAGE, width=TRACE_WIDTH))
        self.curve_max_hold.setVisible(False)
        self.curve_min_hold.setVisible(False)
        self.curve_average.setVisible(False)

    # ------------------------------------------------------------------
    # Marker system
    # ------------------------------------------------------------------
    def _init_markers(self):
        self._last_frequency = None
        self._last_amplitude = None
        self._active_marker_id = 1       # which marker next click places

        # {marker_id: TargetItem}  — placed markers M1/M2/M3
        self._markers: dict = {}
        # {marker_id: TargetItem}  — delta markers M1Δ/M2Δ/M3Δ, one per parent
        self._delta_markers: dict = {}

        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_clicked)

    # --- Active marker selection (called from gui.py dropdown) ---
    def set_active_marker(self, marker_id: int):
        assert marker_id in (1, 2, 3)
        self._active_marker_id = marker_id

    def set_marker_frequency(self, marker_id: int, frequency: float) -> bool:
        """Move a normal marker to the nearest displayed FFT bin."""
        target = self._markers.get(marker_id)
        if target is None or self._last_frequency is None:
            return False
        index = int(np.argmin(np.abs(self._last_frequency - frequency)))
        target.blockSignals(True)
        target.setPos(
            float(self._last_frequency[index]),
            float(self._last_amplitude[index]),
        )
        target.blockSignals(False)
        self._refresh_marker_label(marker_id)
        if marker_id in self._delta_markers:
            self._refresh_delta_label(marker_id)
        self._emit_state()
        return True

    def frequency_at_widget_position(self, position):
        if self._last_frequency is None:
            return None
        plot_position = self.plot_widget.mapFrom(self, position)
        scene_position = self.plot_widget.mapToScene(plot_position)
        data_position = self.plot_widget.getPlotItem().getViewBox().mapSceneToView(scene_position)
        index = int(np.argmin(np.abs(self._last_frequency - data_position.x())))
        return float(self._last_frequency[index])

    def place_active_marker_at_frequency(self, frequency: float):
        if self._last_frequency is None:
            return
        index = int(np.argmin(np.abs(self._last_frequency - frequency)))
        self._place_marker(
            self._active_marker_id,
            float(self._last_frequency[index]),
            float(self._last_amplitude[index]),
        )

    def place_active_marker_at_peak(self):
        if self._last_amplitude is None:
            return
        index = int(np.argmax(self._last_amplitude))
        self._place_marker(
            self._active_marker_id,
            float(self._last_frequency[index]),
            float(self._last_amplitude[index]),
        )

    # --- Place / update a normal marker on click ---
    def _on_plot_clicked(self, event):
        if self._last_frequency is None:
            return
        vb = self.plot_widget.getPlotItem().getViewBox()
        scene_pos = event.scenePos()
        if not self.plot_widget.sceneBoundingRect().contains(scene_pos):
            return
        data_pos = vb.mapSceneToView(scene_pos)
        click_freq = data_pos.x()
        idx = np.argmin(np.abs(self._last_frequency - click_freq))
        self._place_marker(self._active_marker_id,
                           float(self._last_frequency[idx]),
                           float(self._last_amplitude[idx]))

    def _place_marker(self, mid: int, freq: float, amp: float):
        color = MARKER_COLORS[mid]
        label_text = f"M{mid}\n{freq/1e6:.3f} MHz\n{amp:.1f} dBFS"

        if mid not in self._markers:
            target = pg.TargetItem(
                pos=(freq, amp), size=12, movable=True,
                pen=pg.mkPen(color, width=2),
                brush=pg.mkBrush(color),
                label=label_text,
                labelOpts={"color": color, "fill": (0, 0, 0, 180)},
            )
            target.sigPositionChanged.connect(
                lambda t, m=mid: self._on_marker_dragged(m, t))
            self.plot_widget.addItem(target)
            self._markers[mid] = target
        else:
            self._markers[mid].blockSignals(True)
            self._markers[mid].setPos(freq, amp)
            self._markers[mid].blockSignals(False)
            self._refresh_marker_label(mid)

        self._emit_state()

    def _on_marker_dragged(self, mid: int, target):
        """Re-snap to nearest trace sample when dragging a normal marker."""
        if self._last_frequency is None:
            return
        pos = target.pos()
        idx = np.argmin(np.abs(self._last_frequency - pos.x()))
        snapped_freq = float(self._last_frequency[idx])
        snapped_amp  = float(self._last_amplitude[idx])
        if abs(snapped_freq - pos.x()) > 1e-6:
            target.blockSignals(True)
            target.setPos(snapped_freq, snapped_amp)
            target.blockSignals(False)
        self._refresh_marker_label(mid)
        # If this marker has a delta, refresh delta label too
        if mid in self._delta_markers:
            self._refresh_delta_label(mid)
        self._emit_state()

    def _refresh_marker_label(self, mid: int):
        target = self._markers.get(mid)
        if target is None:
            return
        pos = target.pos()
        color = MARKER_COLORS[mid]
        target.setLabel(
            f"M{mid}\n{pos.x()/1e6:.3f} MHz\n{pos.y():.1f} dBFS",
            {"color": color, "fill": (0, 0, 0, 180)}
        )

    # --- Delta marker ---
    def add_delta_marker(self, mid: int):
        """
        Spawns a delta marker for marker `mid`.
        Delta marker = same color as parent, named 'M{mid}Δ'.
        Placed slightly to the right of the parent marker initially.
        Dragging it snaps to the live waveform and shows Δf/ΔA vs the parent.
        """
        if mid not in self._markers:
            return   # parent not placed yet — silently ignore
        if mid in self._delta_markers:
            return   # already exists

        parent_pos = self._markers[mid].pos()
        color = MARKER_COLORS[mid]

        # Initial position: offset by ~5% of visible span to the right
        vb = self.plot_widget.getPlotItem().getViewBox()
        x_range = vb.viewRange()[0]
        offset = (x_range[1] - x_range[0]) * 0.05
        init_freq = parent_pos.x() + offset
        index = int(np.argmin(np.abs(self._last_frequency - init_freq)))
        init_freq = float(self._last_frequency[index])
        init_amp = float(self._last_amplitude[index])

        label_text = self._delta_label_text(mid, init_freq, init_amp)
        delta_target = pg.TargetItem(
            pos=(init_freq, init_amp), size=10, movable=True,
            # Dashed pen to visually distinguish from parent marker
            pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine),
            brush=pg.mkBrush(color + "99"),   # semi-transparent fill
            symbol="d",                         # diamond shape vs crosshair
            label=label_text,
            labelOpts={"color": color, "fill": (0, 0, 0, 180)},
        )
        delta_target.sigPositionChanged.connect(
            lambda t, m=mid: self._on_delta_dragged(m, t))
        self.plot_widget.addItem(delta_target)
        self._delta_markers[mid] = delta_target
        self._emit_state()

    def remove_delta_marker(self, mid: int):
        """Removes the delta marker for marker `mid`."""
        if mid in self._delta_markers:
            self.plot_widget.removeItem(self._delta_markers.pop(mid))
            self._emit_state()

    def _on_delta_dragged(self, mid: int, target):
        """Snap the delta marker to the nearest live-waveform sample."""
        if self._last_frequency is None:
            return
        position = target.pos()
        index = int(np.argmin(np.abs(self._last_frequency - position.x())))
        target.blockSignals(True)
        target.setPos(
            float(self._last_frequency[index]),
            float(self._last_amplitude[index]),
        )
        target.blockSignals(False)
        self._refresh_delta_label(mid)
        self._emit_state()

    def _refresh_delta_label(self, mid: int):
        delta_target = self._delta_markers.get(mid)
        if delta_target is None:
            return
        pos = delta_target.pos()
        color = MARKER_COLORS[mid]
        label_text = self._delta_label_text(mid, pos.x(), pos.y())
        delta_target.setLabel(label_text, {"color": color, "fill": (0, 0, 0, 180)})

    def _delta_label_text(self, mid: int, d_freq: float, d_amp: float) -> str:
        parent = self._markers.get(mid)
        if parent is None:
            return f"M{mid}{DELTA_SYMBOL}"
        p_pos = parent.pos()
        delta_f = d_freq - p_pos.x()
        delta_a = d_amp  - p_pos.y()
        return (f"M{mid}{DELTA_SYMBOL}\n"
                f"{d_freq/1e6:.3f} MHz  {d_amp:.1f} dBFS\n"
                f"{DELTA_SYMBOL}f: {delta_f/1e6:+.3f} MHz\n"
                f"{DELTA_SYMBOL}A: {delta_a:+.1f} dB")

    # --- Clear ---
    def clear_markers(self):
        for t in self._markers.values():
            self.plot_widget.removeItem(t)
        for t in self._delta_markers.values():
            self.plot_widget.removeItem(t)
        self._markers.clear()
        self._delta_markers.clear()
        self._emit_state()

    # --- State emission ---
    def _emit_state(self):
        state = {}
        for mid, target in self._markers.items():
            pos = target.pos()
            delta_info = None
            if mid in self._delta_markers:
                d_pos = self._delta_markers[mid].pos()
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
        self.markers_changed.emit(state)

    # ------------------------------------------------------------------
    # Trace mode toggling
    # ------------------------------------------------------------------
    def set_trace_mode(self, clear_write=None, max_hold=None, min_hold=None, average=None):
        if clear_write is not None:
            self.show_clear_write = clear_write
            self.curve_clear_write.setVisible(clear_write)
        if max_hold is not None:
            self.show_max_hold = max_hold
            self.curve_max_hold.setVisible(max_hold)
        if min_hold is not None:
            self.show_min_hold = min_hold
            self.curve_min_hold.setVisible(min_hold)
        if average is not None:
            self.show_average = average
            self.curve_average.setVisible(average)

    # ------------------------------------------------------------------
    # Frame update (called per FFT frame from gui.py)
    # ------------------------------------------------------------------
    def update_frame(self, frame):
        freq = frame.frequency
        amp  = frame.amplitude
        self._last_frequency = freq
        self._last_amplitude = amp

        # Normal markers stay attached to their selected frequency bin as the
        # live trace changes. This makes marker amplitude a live measurement.
        for mid, target in self._markers.items():
            index = int(np.argmin(np.abs(freq - target.pos().x())))
            target.blockSignals(True)
            target.setPos(float(freq[index]), float(amp[index]))
            target.blockSignals(False)
            self._refresh_marker_label(mid)
            if mid in self._delta_markers:
                delta_target = self._delta_markers[mid]
                delta_index = int(np.argmin(np.abs(freq - delta_target.pos().x())))
                delta_target.blockSignals(True)
                delta_target.setPos(
                    float(freq[delta_index]),
                    float(amp[delta_index]),
                )
                delta_target.blockSignals(False)
                self._refresh_delta_label(mid)

        if self.show_clear_write:
            self.curve_clear_write.setData(freq, amp)
        if self.show_max_hold and frame.max_hold is not None:
            self.curve_max_hold.setData(freq, frame.max_hold)
        if self.show_min_hold and frame.min_hold is not None:
            self.curve_min_hold.setData(freq, frame.min_hold)
        if self.show_average and frame.average is not None:
            self.curve_average.setData(freq, frame.average)

        if self._markers:
            self._emit_state()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------
    def zoom_in(self):
        self.plot_widget.getViewBox().scaleBy((0.8, 0.8))

    def zoom_out(self):
        self.plot_widget.getViewBox().scaleBy((1.25, 1.25))

    def reset_zoom(self):
        self.plot_widget.getViewBox().autoRange()

    def set_reference_level(self, ref_dbm: float, span_db: float = 120):
        self.plot_widget.setYRange(ref_dbm - span_db, ref_dbm)

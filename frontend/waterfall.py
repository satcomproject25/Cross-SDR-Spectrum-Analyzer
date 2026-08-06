import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from .amplitude import raw_trace

COLOR_BACKGROUND = "#000000"
COLOR_AXIS_TEXT = "#CCCCCC"
COLOR_AXIS_LINE = "#666666"
DEFAULT_AMP_MIN = -120.0
DEFAULT_AMP_MAX = 0.0
DEFAULT_HISTORY_DEPTH = 300
LEFT_AXIS_WIDTH = 58


class WaterfallWidget(QWidget):
    """Rolling spectrogram.

    The history buffer always stores RAW dBFS. A unit change only translates
    the intensity-mapping window, so switching between dBFS and dBm neither
    rescales nor invalidates rows already on screen: the picture is identical,
    only the scale it is read against moves. Rewriting 300 x 4096 float32 on
    every unit change would also be a real cost on Pi-class hardware.
    """

    def __init__(self, parent=None, history_depth: int = DEFAULT_HISTORY_DEPTH):
        super().__init__(parent)
        self.history_depth = history_depth
        self._buffer = None
        self._num_bins = None
        self._frequency_bounds = None
        # Intensity window, expressed in the CURRENTLY DISPLAYED unit.
        self._amp_min = DEFAULT_AMP_MIN
        self._amp_max = DEFAULT_AMP_MAX
        # Injected by MainWindow; never derived from the frame here, so the
        # waterfall cannot disagree with the spectrum axis.
        self._amp_unit = "dBFS"
        self._amp_offset_db = 0.0
        self._build_plot()

    def _build_plot(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(COLOR_BACKGROUND)
        plot_item = self.plot_widget.getPlotItem()
        plot_item.setLabel(
            "bottom", "Frequency", units="Hz", color=COLOR_AXIS_TEXT
        )
        plot_item.setLabel("left", "Time (frames ago)", color=COLOR_AXIS_TEXT)
        for axis_name in ("bottom", "left"):
            axis = plot_item.getAxis(axis_name)
            axis.setTextPen(COLOR_AXIS_TEXT)
            axis.setPen(COLOR_AXIS_LINE)
        plot_item.getAxis("left").setWidth(LEFT_AXIS_WIDTH)
        plot_item.invertY(True)
        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)
        colormap = pg.colormap.get("viridis")
        self.image_item.setColorMap(colormap)
        layout.addWidget(self.plot_widget)

    def link_frequency_axis(self, spectrum_plot_widget):
        """Follow another plot\'s horizontal range while retaining time Y zoom."""
        source_plot = spectrum_plot_widget.getPlotItem()
        self.plot_widget.getPlotItem().setXLink(source_plot)
        self.plot_widget.getViewBox().setMouseEnabled(x=False, y=True)

    # ------------------------------------------------------------------
    # Buffer
    # ------------------------------------------------------------------
    def _raw_floor(self) -> float:
        """`_amp_min` expressed in the buffer\'s raw dBFS domain."""
        return self._amp_min - self._amp_offset_db

    def _allocate_buffer(self, num_bins: int):
        self._num_bins = num_bins
        self._buffer = np.full(
            (self.history_depth, num_bins), self._raw_floor(), dtype=np.float32
        )

    def _refresh_image(self):
        if self._buffer is None:
            return
        shift = self._amp_offset_db
        self.image_item.setImage(
            self._buffer.T,
            levels=(self._amp_min - shift, self._amp_max - shift),
            autoLevels=False,
        )

    def update_frame(self, frame):
        # Force the raw dBFS trace regardless of display unit: the offset is
        # applied once, at the levels= mapping, not per stored sample.
        amplitude = raw_trace(frame, "amplitude")
        frequency = frame.frequency
        num_bins = amplitude.shape[0]
        geometry_changed = False
        if self._buffer is None or self._num_bins != num_bins:
            self._allocate_buffer(num_bins)
            geometry_changed = True
        frequency_bounds = (float(frequency[0]), float(frequency[-1]))
        if frequency_bounds != self._frequency_bounds:
            self._frequency_bounds = frequency_bounds
            geometry_changed = True
        self._buffer = np.roll(self._buffer, 1, axis=0)
        self._buffer[0, :] = amplitude
        self._refresh_image()
        # setRect derives its per-pixel scale from the image dimensions. It
        # must run after setImage has installed the actual FFT/history shape.
        if geometry_changed:
            self._set_x_scale(frequency)

    def _set_x_scale(self, frequency: np.ndarray):
        freq_start = float(frequency[0])
        freq_end = float(frequency[-1])
        if frequency.size > 1:
            bin_width = float(np.median(np.diff(frequency)))
        else:
            bin_width = 1.0
        # Image pixels represent FFT bins; placing the rectangle edges half a
        # bin outside makes every waterfall pixel center match its trace bin.
        image_start = freq_start - bin_width / 2.0
        image_span = freq_end - freq_start + bin_width
        self.image_item.resetTransform()
        self.image_item.setRect(image_start, 0, image_span, self.history_depth)

    # ------------------------------------------------------------------
    # Amplitude scale
    # ------------------------------------------------------------------
    def set_amplitude_range(self, amp_min: float, amp_max: float):
        """Set the intensity window, in the currently displayed unit."""
        self._amp_min = float(amp_min)
        self._amp_max = float(amp_max)
        if self._buffer is not None:
            self._buffer.fill(self._raw_floor())
            self._refresh_image()

    def amplitude_range(self) -> tuple[float, float]:
        return self._amp_min, self._amp_max

    def set_amplitude_unit(self, unit: str, offset_db: float = 0.0):
        """Adopt a new display unit and offset without discarding history.

        The window is translated by the offset delta so the same physical
        levels keep the same colours across a unit switch.
        """
        previous = self._amp_offset_db
        self._amp_unit = unit
        self._amp_offset_db = float(offset_db)
        delta = self._amp_offset_db - previous
        if delta:
            self._amp_min += delta
            self._amp_max += delta
        self.plot_widget.getPlotItem().setLabel(
            "left", f"Time (frames ago) - {unit}", color=COLOR_AXIS_TEXT
        )
        self._refresh_image()

    def amplitude_unit(self) -> str:
        return self._amp_unit

    def clear(self):
        if self._buffer is not None:
            self._buffer.fill(self._raw_floor())
            self._refresh_image()
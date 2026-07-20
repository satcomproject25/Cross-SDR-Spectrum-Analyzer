import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

COLOR_BACKGROUND = "#000000"
COLOR_AXIS_TEXT = "#CCCCCC"
COLOR_AXIS_LINE = "#666666"
DEFAULT_AMP_MIN = -120.0
DEFAULT_AMP_MAX = 0.0
DEFAULT_HISTORY_DEPTH = 300
LEFT_AXIS_WIDTH = 58


class WaterfallWidget(QWidget):
    def __init__(self, parent=None, history_depth: int = DEFAULT_HISTORY_DEPTH):
        super().__init__(parent)
        self.history_depth = history_depth
        self._buffer = None
        self._num_bins = None
        self._frequency_bounds = None
        self._amp_min = DEFAULT_AMP_MIN
        self._amp_max = DEFAULT_AMP_MAX
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
        """Follow another plot's horizontal range while retaining time Y zoom."""
        source_plot = spectrum_plot_widget.getPlotItem()
        self.plot_widget.getPlotItem().setXLink(source_plot)
        self.plot_widget.getViewBox().setMouseEnabled(x=False, y=True)

    def _allocate_buffer(self, num_bins: int):
        self._num_bins = num_bins
        self._buffer = np.full((self.history_depth, num_bins), self._amp_min, dtype=np.float32)

    def update_frame(self, frame):
        amplitude = frame.amplitude
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
        self.image_item.setImage(self._buffer.T, levels=(self._amp_min, self._amp_max), autoLevels=False)
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

    def set_amplitude_range(self, amp_min: float, amp_max: float):
        self._amp_min = amp_min
        self._amp_max = amp_max
        if self._buffer is not None:
            self._buffer.fill(amp_min)

    def clear(self):
        if self._buffer is not None:
            self._buffer.fill(self._amp_min)
            self.image_item.setImage(self._buffer.T, levels=(self._amp_min, self._amp_max), autoLevels=False)

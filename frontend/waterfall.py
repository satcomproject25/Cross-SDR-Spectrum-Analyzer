import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

COLOR_BACKGROUND = "#000000"
COLOR_AXIS_TEXT = "#CCCCCC"
COLOR_AXIS_LINE = "#666666"
DEFAULT_AMP_MIN = -120.0
DEFAULT_AMP_MAX = 0.0
DEFAULT_HISTORY_DEPTH = 300


class WaterfallWidget(QWidget):
    def __init__(self, parent=None, history_depth: int = DEFAULT_HISTORY_DEPTH):
        super().__init__(parent)
        self.history_depth = history_depth
        self._buffer = None
        self._num_bins = None
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
        plot_item.invertY(True)
        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)
        colormap = pg.colormap.get("viridis")
        self.image_item.setColorMap(colormap)
        layout.addWidget(self.plot_widget)

    def _allocate_buffer(self, num_bins: int):
        self._num_bins = num_bins
        self._buffer = np.full((self.history_depth, num_bins), self._amp_min, dtype=np.float32)

    def update_frame(self, frame):
        amplitude = frame.amplitude
        frequency = frame.frequency
        num_bins = amplitude.shape[0]
        if self._buffer is None or self._num_bins != num_bins:
            self._allocate_buffer(num_bins)
            self._set_x_scale(frequency)
        self._buffer = np.roll(self._buffer, 1, axis=0)
        self._buffer[0, :] = amplitude
        self.image_item.setImage(self._buffer.T, levels=(self._amp_min, self._amp_max), autoLevels=False)

    def _set_x_scale(self, frequency: np.ndarray):
        freq_start = frequency[0]
        freq_end = frequency[-1]
        freq_span = freq_end - freq_start
        self.image_item.resetTransform()
        self.image_item.setRect(freq_start, 0, freq_span, self.history_depth)

    def set_amplitude_range(self, amp_min: float, amp_max: float):
        self._amp_min = amp_min
        self._amp_max = amp_max
        if self._buffer is not None:
            self._buffer.fill(amp_min)

    def clear(self):
        if self._buffer is not None:
            self._buffer.fill(self._amp_min)
            self.image_item.setImage(self._buffer.T, levels=(self._amp_min, self._amp_max), autoLevels=False)

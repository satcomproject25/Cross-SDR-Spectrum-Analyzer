import os
import types
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from backend.carrier_detection import CarrierRegion
from frontend.renderer import (
    COLOR_AUTO_PEAK,
    COLOR_AVERAGE,
    COLOR_AXIS_TEXT,
    COLOR_BACKGROUND,
    COLOR_CLEAR_WRITE,
    COLOR_MAX_HOLD,
    COLOR_MIN_HOLD,
    MARKER_COLORS,
    SpectrumWidget,
)


class SpectrumWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = SpectrumWidget()
        self.frame = types.SimpleNamespace(
            frequency=np.array([100.0, 200.0, 300.0, 400.0]),
            amplitude=np.array([-40.0, -20.0, -30.0, -35.0]),
            max_hold=np.array([-25.0, -10.0, -18.0, -20.0]),
            min_hold=np.array([-60.0, -45.0, -55.0, -50.0]),
            average=np.array([-35.0, -15.0, -25.0, -30.0]),
        )
        self.widget.update_frame(self.frame)

    def tearDown(self):
        self.widget.close()

    def test_auto_peak_marker_tracks_selected_trace_global_peak_and_owns_red(self):
        trace_frame = types.SimpleNamespace(
            frequency=self.frame.frequency,
            amplitude=np.array([-10.0, -40.0, -50.0, -60.0]),
            max_hold=np.array([-50.0, -9.0, -40.0, -60.0]),
            min_hold=np.array([-70.0, -65.0, -30.0, -80.0]),
            average=np.array([-45.0, -50.0, -55.0, -8.0]),
        )
        self.widget.update_frame(trace_frame)

        expected_peaks = {
            "cw": (100.0, -10.0),
            "max_hold": (200.0, -9.0),
            "min_hold": (300.0, -30.0),
            "average": (400.0, -8.0),
        }
        for trace_name, expected in expected_peaks.items():
            with self.subTest(trace=trace_name):
                self.widget.set_marker_trace(trace_name)
                x_data, y_data = self.widget.auto_peak_marker.getData()
                self.assertEqual(float(x_data[0]), expected[0])
                self.assertEqual(float(y_data[0]), expected[1])

        self.assertEqual(COLOR_AUTO_PEAK, "#FF3B30")
        self.assertNotEqual(COLOR_MAX_HOLD, COLOR_AUTO_PEAK)

    def test_all_spectrum_features_contrast_with_black_background(self):
        self.assertEqual(COLOR_BACKGROUND, "#000000")
        visible_colors = {
            COLOR_CLEAR_WRITE,
            COLOR_MAX_HOLD,
            COLOR_MIN_HOLD,
            COLOR_AVERAGE,
            COLOR_AXIS_TEXT,
            *MARKER_COLORS.values(),
        }
        self.assertNotIn(COLOR_BACKGROUND, visible_colors)

    def test_normal_and_delta_markers_follow_only_selected_trace(self):
        self.widget.set_active_marker(1)
        self.widget.place_active_marker_at_frequency(200.0)
        self.widget.add_delta_marker(1)
        delta_frequency = float(self.widget._delta_markers[1].pos().x())
        delta_index = int(np.argmin(np.abs(self.frame.frequency - delta_frequency)))

        self.widget.set_marker_trace("max_hold")

        self.assertEqual(self.widget.marker_trace, "max_hold")
        self.assertEqual(float(self.widget._markers[1].pos().y()), -10.0)
        self.assertEqual(
            float(self.widget._delta_markers[1].pos().y()),
            float(self.frame.max_hold[delta_index]),
        )

        next_frame = types.SimpleNamespace(
            frequency=self.frame.frequency,
            amplitude=np.full(4, -90.0),
            max_hold=np.array([-24.0, -9.0, -17.0, -19.0]),
            min_hold=np.full(4, -100.0),
            average=np.full(4, -70.0),
        )
        self.widget.update_frame(next_frame)
        self.assertEqual(float(self.widget._markers[1].pos().y()), -9.0)
        self.assertEqual(
            float(self.widget._delta_markers[1].pos().y()),
            float(next_frame.max_hold[delta_index]),
        )

    def test_peak_search_uses_selected_marker_trace(self):
        self.widget.set_active_marker(1)
        self.widget.set_marker_trace("min_hold")
        self.widget.place_active_marker_at_peak()
        marker = self.widget._markers[1].pos()
        self.assertEqual(float(marker.x()), 200.0)
        self.assertEqual(float(marker.y()), -45.0)

    def test_none_marker_selection_disables_all_placement_paths(self):
        self.widget.place_active_marker_at_frequency(200.0)
        self.widget.place_active_marker_at_peak()
        self.assertEqual(self.widget._markers, {})

        self.widget.set_active_marker(2)
        self.widget.place_active_marker_at_frequency(200.0)
        self.assertIn(2, self.widget._markers)

    def test_carrier_regions_align_to_detected_edge_bins_and_are_reused(self):
        self.frame.carriers = [
            CarrierRegion(0, 1, 0, 1, -20.0, -80.0),
            CarrierRegion(2, 3, 2, 2, -25.0, -80.0),
        ]
        self.widget.update_frame(self.frame)

        self.assertEqual(len(self.widget._carrier_regions), 2)
        self.assertEqual(
            tuple(self.widget._carrier_regions[0].getRegion()),
            (100.0, 200.0),
        )
        first_region = self.widget._carrier_regions[0]

        self.frame.carriers = [CarrierRegion(1, 2, 1, 1, -20.0, -80.0)]
        self.widget.update_frame(self.frame)
        self.assertIs(self.widget._carrier_regions[0], first_region)
        self.assertEqual(
            tuple(self.widget._carrier_regions[0].getRegion()),
            (200.0, 300.0),
        )
        self.assertFalse(self.widget._carrier_regions[1].isVisible())


if __name__ == "__main__":
    unittest.main()

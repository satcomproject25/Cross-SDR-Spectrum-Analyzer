import os
import types
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from frontend.gui import MainWindow


class MainWindowProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_professional_layout_keeps_controls_in_analysis_tabs(self):
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.window.analysis_tabs.count(), 3)
        self.assertEqual(
            [self.window.analysis_tabs.tabText(i) for i in range(3)],
            ["Measure", "Traces", "Markers"],
        )
        tab_bar = self.window.analysis_tabs.tabBar()
        widths = [tab_bar.tabRect(i).width() for i in range(tab_bar.count())]
        self.assertLessEqual(max(widths) - min(widths), 1)

    def test_side_panels_collapse_and_restore_from_persistent_edge_handles(self):
        self.window.show()
        self.app.processEvents()
        initial_central_width = self.window.centralWidget().width()

        self.window.btn_left_panel_toggle.click()
        self.window.btn_right_panel_toggle.click()
        self.app.processEvents()

        self.assertFalse(self.window.left_dock.isVisible())
        self.assertFalse(self.window.right_dock.isVisible())
        self.assertTrue(self.window.btn_left_panel_toggle.isVisible())
        self.assertTrue(self.window.btn_right_panel_toggle.isVisible())
        self.assertEqual(self.window.btn_left_panel_toggle.text(), "›")
        self.assertEqual(self.window.btn_right_panel_toggle.text(), "‹")
        self.assertEqual(self.window.btn_left_panel_toggle.x(), 0)
        self.assertEqual(
            self.window.btn_right_panel_toggle.geometry().right(),
            self.window.width() - 1,
        )
        self.assertGreater(self.window.centralWidget().width(), initial_central_width)

        self.window.btn_left_panel_toggle.click()
        self.window.btn_right_panel_toggle.click()
        self.app.processEvents()
        self.assertTrue(self.window.left_dock.isVisible())
        self.assertTrue(self.window.right_dock.isVisible())
        self.assertEqual(self.window.btn_left_panel_toggle.text(), "‹")
        self.assertEqual(self.window.btn_right_panel_toggle.text(), "›")

    def test_none_is_default_and_disables_marker_placement(self):
        self.assertEqual(self.window.marker_selector_btn.current_marker_id(), 0)
        self.assertFalse(self.window.btn_delta_marker.isEnabled())
        self.assertIsNone(self.window.spectrum_widget._active_marker_id)

    def test_waterfall_frequency_range_follows_spectrum_zoom_and_reset(self):
        frequency = np.linspace(60e6, 80e6, 256)
        amplitude = np.full(256, -80.0)
        frame = types.SimpleNamespace(
            frequency=frequency,
            amplitude=amplitude,
            max_hold=amplitude.copy(),
            min_hold=amplitude.copy(),
            average=amplitude.copy(),
            carriers=[],
        )
        self.window.spectrum_widget.update_frame(frame)
        self.window.waterfall_widget.update_frame(frame)
        self.app.processEvents()

        waterfall = self.window.waterfall_widget
        image_rect = waterfall.image_item.mapRectToParent(
            waterfall.image_item.boundingRect()
        )
        bin_width = frequency[1] - frequency[0]
        self.assertAlmostEqual(image_rect.left(), frequency[0] - bin_width / 2.0)
        self.assertAlmostEqual(image_rect.right(), frequency[-1] + bin_width / 2.0)
        self.assertAlmostEqual(image_rect.top(), 0.0)
        self.assertAlmostEqual(image_rect.bottom(), waterfall.history_depth)

        spectrum_view = self.window.spectrum_widget.plot_widget.getViewBox()
        waterfall_view = self.window.waterfall_widget.plot_widget.getViewBox()
        spectrum_view.setXRange(68e6, 72e6, padding=0)
        self.app.processEvents()
        self.assertTrue(
            np.allclose(
                waterfall_view.viewRange()[0],
                spectrum_view.viewRange()[0],
            )
        )

        waterfall_view.autoRange(padding=0)
        self.app.processEvents()
        waterfall_range = waterfall_view.viewRange()[0]
        self.assertLess(waterfall_range[1], 100e6)
        self.assertGreater(waterfall_range[0], 40e6)
        self.assertTrue(np.allclose(waterfall_range, spectrum_view.viewRange()[0]))

        shifted_frequency = frequency + 20e6
        frame.frequency = shifted_frequency
        self.window.spectrum_widget.update_frame(frame)
        self.window.waterfall_widget.update_frame(frame)
        self.assertEqual(
            self.window.waterfall_widget._frequency_bounds,
            (float(shifted_frequency[0]), float(shifted_frequency[-1])),
        )

        self.window.spectrum_widget.reset_zoom()
        self.app.processEvents()
        self.assertTrue(
            np.allclose(
                waterfall_view.viewRange()[0],
                spectrum_view.viewRange()[0],
            )
        )

    def test_x301_and_hackrf_profiles_restore_documented_limits(self):
        self.window.sdr_type_combo.setCurrentIndex(
            self.window.sdr_type_combo.findData("USRP")
        )
        usrp = self.window._acquisition_config()
        self.assertEqual(usrp.sample_rate, 200e6)
        self.assertEqual(usrp.span, 160e6)
        self.assertEqual(self.window.span_ctrl._max_hz, 160e6)
        self.assertEqual(self.window.sample_rate_combo.itemText(
            self.window.sample_rate_combo.count() - 1
        ), "200")
        self.window.sample_rate_combo.setCurrentText("100")
        self.assertEqual(self.window.span_ctrl._max_hz, 100e6)
        self.assertEqual(self.window._acquisition_config().span, 100e6)

        self.window.sdr_type_combo.setCurrentIndex(
            self.window.sdr_type_combo.findData("HACKRF")
        )
        hackrf = self.window._acquisition_config()
        self.assertEqual(hackrf.sample_rate, 20e6)
        self.assertEqual(hackrf.span, 20e6)
        self.assertEqual(self.window.span_ctrl._max_hz, 20e6)
        self.assertEqual(self.window.sample_rate_combo.itemText(
            self.window.sample_rate_combo.count() - 1
        ), "20")

    def test_pluto_profile_exposes_supported_limits(self):
        self.window.sdr_type_combo.setCurrentIndex(
            self.window.sdr_type_combo.findData("PLUTO")
        )
        pluto = self.window._acquisition_config()
        self.assertEqual(pluto.device_type, "PLUTO")
        self.assertEqual(pluto.sample_rate, 4e6)
        self.assertEqual(pluto.span, 4e6)
        self.assertEqual(self.window.center_freq_ctrl._min_hz, 325e6)
        self.assertEqual(self.window.center_freq_ctrl._max_hz, 3.8e9)
        self.assertEqual(self.window.span_ctrl._max_hz, 20e6)
        self.assertEqual(self.window.sample_rate_combo.itemText(
            self.window.sample_rate_combo.count() - 1
        ), "61.44")

    def test_calibrated_frame_updates_measurements_and_status_in_dbm(self):
        frequency = np.linspace(100e6, 101e6, 16)
        raw = np.linspace(-90.0, -30.0, 16)
        calibrated = raw + 42.0
        peak = types.SimpleNamespace(
            frequency=float(frequency[-1]),
            amplitude=float(raw[-1]),
        )
        peak_dbm = types.SimpleNamespace(
            frequency=float(frequency[-1]),
            amplitude=float(calibrated[-1]),
        )
        frame = types.SimpleNamespace(
            frequency=frequency,
            amplitude=raw,
            max_hold=raw.copy(),
            min_hold=raw.copy(),
            average=raw.copy(),
            amplitude_dbm=calibrated,
            max_hold_dbm=calibrated.copy(),
            min_hold_dbm=calibrated.copy(),
            average_dbm=calibrated.copy(),
            peaks=[peak],
            peaks_dbm=[peak_dbm],
            noise_floor=float(np.median(raw)),
            noise_floor_dbfs=float(np.median(raw)),
            noise_floor_dbm=float(np.median(calibrated)),
            channel_power=-20.0,
            channel_power_dbfs=-20.0,
            channel_power_dbm=22.0,
            bandwidth=500e3,
            fft_size=4096,
            rbw=1e3,
            carriers=[],
        )

        self.window._on_frame_ready(frame)

        self.assertEqual(self.window.lbl_peak_status.text(), "Peak: 12.00 dBm")
        self.assertEqual(self.window.lbl_meas_peak_amp.text(), "12.00 dBm")
        self.assertEqual(self.window.lbl_meas_noise.text(), "-18.00 dBm")
        self.assertEqual(self.window.lbl_meas_chan_pwr.text(), "22.00 dBm")
        self.assertEqual(self.window.spectrum_widget._amplitude_unit, "dBm")
        self.assertEqual(self.window.delta_readout._amplitude_unit, "dBm")
        self.assertEqual(self.window.reference_level_spin.suffix(), " dBm")
        self.assertTrue(np.array_equal(self.window.waterfall_widget._buffer[0], calibrated))

        self.window._update_marker_table(
            {
                1: {
                    "frequency": float(frequency[-1]),
                    "amplitude": float(calibrated[-1]),
                    "delta": None,
                }
            }
        )
        self.assertEqual(self.window.table_markers.item(0, 2).text(), "12.00 dBm")


if __name__ == "__main__":
    unittest.main()

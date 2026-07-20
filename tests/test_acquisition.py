import types
import unittest
from unittest.mock import patch

import numpy as np

from backend.acquisition import (
    AcquisitionError,
    HackRFAcquisition,
    SyntheticAcquisition,
    SoapyAcquisition,
    USRPAcquisition,
    create_acquisition,
)
from backend.models import AcquisitionConfig
from backend.sdr import SDR


class FakeRange:
    def minimum(self):
        return 0.0

    def maximum(self):
        return 60.0


class FakeDevice:
    @staticmethod
    def enumerate(*_):
        return [{"driver": "hackrf", "label": "Fake HackRF", "serial": "123"}]

    def __init__(self, _):
        self.sample_rate = 0.0
        self.frequency = 0.0

    def setSampleRate(self, _, __, value):
        self.sample_rate = value

    def getSampleRate(self, _, __):
        return self.sample_rate

    def setFrequency(self, _, __, value):
        self.frequency = value

    def getFrequency(self, _, __):
        return self.frequency

    def hasGainMode(self, _, __):
        return True

    def setGainMode(self, *_):
        pass

    def getGainRange(self, *_):
        return FakeRange()

    def setGain(self, *_):
        pass

    def setupStream(self, *_):
        return object()

    def activateStream(self, *_):
        return 0

    def readStream(self, _, buffers, length, **__):
        n = np.arange(length)
        buffers[0][:] = np.exp(2j * np.pi * n / max(length, 1))
        return types.SimpleNamespace(ret=length)

    def deactivateStream(self, *_):
        pass

    def closeStream(self, *_):
        pass


class FakeUSRPDevice(FakeDevice):
    last_instance = None

    @staticmethod
    def enumerate(hint=None):
        if hint and hint.get("driver") == "uhd":
            return [
                {
                    "driver": "uhd",
                    "label": "Fake B200",
                    "serial": "U123",
                    "type": "b200",
                }
            ]
        return []

    @staticmethod
    def unmake(_):
        pass

    def __init__(self, selector):
        super().__init__(selector)
        self.selector = selector
        self.bandwidth = None
        self.gain = None
        FakeUSRPDevice.last_instance = self

    def setBandwidth(self, _, __, value):
        self.bandwidth = value

    def setGain(self, _, __, value):
        self.gain = value


class AcquisitionTests(unittest.TestCase):
    def test_x300_profile_rejects_unsupported_rate_and_span(self):
        with self.assertRaises(AcquisitionError):
            USRPAcquisition(
                AcquisitionConfig("USRP", 915e6, 201e6, 160e6, 20)
            )
        with self.assertRaises(AcquisitionError):
            USRPAcquisition(
                AcquisitionConfig("USRP", 915e6, 200e6, 161e6, 20)
            )

    def test_factory_keeps_hackrf_and_usrp_paths_separate_when_switching(self):
        hackrf = AcquisitionConfig("HACKRF", 100e6, 2e6, 2e6, 20)
        usrp = AcquisitionConfig("USRP", 100e6, 2e6, 2e6, 20)

        first_hackrf = create_acquisition(hackrf)
        selected_usrp = create_acquisition(usrp)
        second_hackrf = create_acquisition(hackrf)

        self.assertIsInstance(first_hackrf, HackRFAcquisition)
        self.assertIsInstance(selected_usrp, USRPAcquisition)
        self.assertIsInstance(second_hackrf, HackRFAcquisition)
        self.assertIsNot(first_hackrf, second_hackrf)

    def test_usrp_is_discovered_configured_and_streamed_only_on_run(self):
        FakeUSRPDevice.last_instance = None
        fake_soapy = types.SimpleNamespace(
            Device=FakeUSRPDevice,
            SOAPY_SDR_RX=1,
            SOAPY_SDR_CF32="CF32",
            SOAPY_SDR_TIMEOUT=-1,
            SOAPY_SDR_OVERFLOW=-4,
        )
        config = AcquisitionConfig("USRP", 915e6, 2e6, 1e6, 20, fft_size=4096)
        acquisition = create_acquisition(config)
        self.assertIsNone(FakeUSRPDevice.last_instance)
        frames = []

        def receive(frame):
            frames.append(frame)
            acquisition.stop()

        with patch("backend.acquisition._load_soapy", return_value=fake_soapy):
            acquisition.run(receive)

        device = FakeUSRPDevice.last_instance
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].device_name, "Fake B200")
        self.assertEqual(device.selector, "driver=uhd,serial=U123")
        self.assertEqual(device.sample_rate, 2e6)
        self.assertEqual(device.frequency, 915e6)
        self.assertEqual(device.bandwidth, 1e6)
        self.assertEqual(device.gain, 20)

    def test_stream_reaches_frontend_callback_and_closes(self):
        fake_soapy = types.SimpleNamespace(
            Device=FakeDevice,
            SOAPY_SDR_RX=1,
            SOAPY_SDR_CF32="CF32",
            SOAPY_SDR_TIMEOUT=-1,
            SOAPY_SDR_OVERFLOW=-4,
        )
        config = AcquisitionConfig("HACKRF", 100e6, 2e6, 2e6, 20, fft_size=4096)
        acquisition = SoapyAcquisition(config)
        frames = []
        statuses = []

        def receive(frame):
            frames.append(frame)
            acquisition.stop()

        with patch("backend.acquisition._load_soapy", return_value=fake_soapy):
            with patch(
                "backend.acquisition.load_device_calibration",
                return_value={"frequency_axis_offset_hz": 0.0},
            ):
                acquisition.run(receive, statuses.append)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].device_name, "Fake HackRF")
        self.assertTrue(statuses[0].startswith("Connected:"))
        self.assertEqual(statuses[-1], "Idle")

    def test_hackrf_frequency_axis_uses_calibrated_driver_readback(self):
        fake_soapy = types.SimpleNamespace(
            Device=FakeDevice,
            SOAPY_SDR_RX=1,
            SOAPY_SDR_CF32="CF32",
            SOAPY_SDR_TIMEOUT=-1,
            SOAPY_SDR_OVERFLOW=-4,
        )
        config = AcquisitionConfig("HACKRF", 2.44e9, 2e6, 2e6, 20, fft_size=4096)
        acquisition = HackRFAcquisition(config)
        frames = []

        def receive(frame):
            frames.append(frame)
            acquisition.stop()

        with patch("backend.acquisition._load_soapy", return_value=fake_soapy), patch(
            "backend.acquisition.load_device_calibration",
            return_value={"frequency_axis_offset_hz": -22000.0},
        ):
            acquisition.run(receive)

        self.assertEqual(acquisition.config.center_frequency, 2.44e9 - 22000.0)
        self.assertAlmostEqual(
            (frames[0].frequency[0] + frames[0].frequency[-1]) / 2.0,
            2.44e9 - 22000.0 - acquisition.config.sample_rate / 8192.0,
            places=3,
        )

    def test_sdr_configure_receive_sets_rx_parameters(self):
        fake_soapy = types.SimpleNamespace(
            Device=FakeDevice,
            SOAPY_SDR_RX=1,
            SOAPY_SDR_CF32="CF32",
        )
        with patch("backend.sdr._load_soapy", return_value=fake_soapy), patch(
            "backend.sdr.enumerate_devices",
            return_value=[
                {
                    "driver": "hackrf",
                    "label": "Fake HackRF",
                    "serial": "123",
                    "hardware": "FakeHardware",
                }
            ],
        ):
            info = SDR().configure_receive("HACKRF", 100e6, 2e6, 20, channel=0)

        self.assertTrue(info.connected)
        self.assertEqual(info.device_name, "Fake HackRF")
        self.assertEqual(info.driver, "hackrf")
        self.assertEqual(info.serial_number, "123")
        self.assertEqual(info.details["configured_center_frequency"], "100000000.0")
        self.assertEqual(info.details["configured_sample_rate"], "2000000.0")
        self.assertEqual(float(info.details["configured_gain"]), 20.0)

    def test_sdr_diagnostic_uses_uhd_selector_and_generic_usrp_gain(self):
        fake_soapy = types.SimpleNamespace(
            Device=FakeUSRPDevice,
            SOAPY_SDR_RX=1,
            SOAPY_SDR_CF32="CF32",
        )
        match = {
            "driver": "uhd",
            "label": "Fake B200",
            "serial": "U123",
            "type": "b200",
        }
        with patch("backend.sdr._load_soapy", return_value=fake_soapy), patch(
            "backend.sdr.enumerate_devices", return_value=[match]
        ):
            info = SDR().configure_receive("USRP", 915e6, 2e6, 20, channel=0)

        device = FakeUSRPDevice.last_instance
        self.assertEqual(device.selector, "driver=uhd,serial=U123")
        self.assertEqual(device.gain, 20)
        self.assertEqual(info.driver, "uhd")
        self.assertEqual(info.hardware_key, "b200")

    def test_realtime_simulator_uses_normal_pipeline(self):
        config = AcquisitionConfig("SIMULATOR", 2.44e9, 20e6, 20e6, 20, fft_size=4096)
        acquisition = create_acquisition(config)
        self.assertIsInstance(acquisition, SyntheticAcquisition)
        acquisition.frame_rate = 1000.0
        frames = []
        statuses = []

        def receive(frame):
            frames.append(frame)
            if len(frames) == 16:
                acquisition.stop()

        acquisition.run(receive, statuses.append)

        self.assertEqual(len(frames), 16)
        frame = frames[-1]
        self.assertEqual(frame.frame_count, 16)
        self.assertEqual(frame.device_name, "Built-in IQ Simulator")
        self.assertGreaterEqual(len(frame.peaks), 2)
        self.assertTrue(np.any(frame.max_hold > frame.min_hold))

        # The averaged spectrum contains two nearby, occupied digital bands,
        # not merely two isolated CW bins.
        average_noise = float(np.median(frame.average))
        occupied = np.flatnonzero(frame.average > average_noise + 15.0)
        groups = 1 + int(np.count_nonzero(np.diff(occupied) > 1))
        self.assertGreater(len(occupied), 300)
        self.assertEqual(groups, 2)
        self.assertEqual(len(frame.carriers), 2)
        offsets = frame.frequency[occupied] - config.center_frequency
        self.assertTrue(np.all(np.abs(offsets) < 2e6))
        self.assertTrue(statuses[0].startswith("Connected:"))
        self.assertEqual(statuses[-1], "Idle")


if __name__ == "__main__":
    unittest.main()

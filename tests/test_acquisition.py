import types
import unittest
from unittest.mock import patch

import numpy as np

from backend.acquisition import SyntheticAcquisition, SoapyAcquisition, create_acquisition
from backend.models import AcquisitionConfig


class FakeRange:
    def minimum(self):
        return 0.0

    def maximum(self):
        return 60.0


class FakeDevice:
    @staticmethod
    def enumerate():
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
        pass

    def readStream(self, _, buffers, length, **__):
        n = np.arange(length)
        buffers[0][:] = np.exp(2j * np.pi * n / max(length, 1))
        return types.SimpleNamespace(ret=length)

    def deactivateStream(self, *_):
        pass

    def closeStream(self, *_):
        pass


class AcquisitionTests(unittest.TestCase):
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
            acquisition.run(receive, statuses.append)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].device_name, "Fake HackRF")
        self.assertTrue(statuses[0].startswith("Connected:"))
        self.assertEqual(statuses[-1], "Idle")

    def test_realtime_simulator_uses_normal_pipeline(self):
        config = AcquisitionConfig("SIMULATOR", 2.44e9, 20e6, 20e6, 20, fft_size=4096)
        acquisition = create_acquisition(config)
        self.assertIsInstance(acquisition, SyntheticAcquisition)
        acquisition.frame_rate = 120.0
        frames = []
        statuses = []

        def receive(frame):
            frames.append(frame)
            if len(frames) == 4:
                acquisition.stop()

        acquisition.run(receive, statuses.append)

        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[-1].frame_count, 4)
        self.assertEqual(frames[-1].device_name, "Built-in IQ Simulator")
        self.assertGreaterEqual(len(frames[-1].peaks), 2)
        self.assertTrue(np.any(frames[-1].max_hold > frames[-1].min_hold))
        self.assertTrue(statuses[0].startswith("Connected:"))
        self.assertEqual(statuses[-1], "Idle")


if __name__ == "__main__":
    unittest.main()

import json
import os
import unittest

import numpy as np
from fastapi.testclient import TestClient

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from backend.controller import AnalyzerPipeline
from backend.models import AcquisitionConfig
from webapp.protocol import pack_spectrum_frame, unpack_spectrum_frame
from webapp.server import AnalyzerCoordinator, create_app


class WebProtocolTests(unittest.TestCase):
    def test_binary_frame_preserves_calibrated_traces_and_metadata(self):
        config = AcquisitionConfig(
            "SIMULATOR", 2.44e9, 2e6, 1e6, 20, fft_size=4096
        )
        pipeline = AnalyzerPipeline(
            config, "Web test SDR", power_offset_db=35.0
        )
        n = np.arange(config.fft_size)
        samples = (
            0.5
            * np.exp(2j * np.pi * 125e3 * n / config.sample_rate)
        ).astype(np.complex64)
        frame = pipeline.process(samples)

        header, traces = unpack_spectrum_frame(pack_spectrum_frame(frame))

        self.assertEqual(header["unit"], "dBm")
        self.assertEqual(header["device_name"], "Web test SDR")
        self.assertEqual(header["bins"], frame.frequency.size)
        self.assertTrue(
            np.allclose(traces["amplitude"], frame.amplitude_dbm)
        )
        self.assertTrue(
            np.allclose(traces["max_hold"], frame.max_hold_dbm)
        )
        self.assertAlmostEqual(
            header["frequency_start"], float(frame.frequency[0])
        )


class WebApplicationTests(unittest.TestCase):
    def test_static_ui_profiles_and_token_protection(self):
        coordinator = AnalyzerCoordinator()
        with TestClient(create_app(coordinator, access_token="campus-secret")) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/profiles").status_code, 401)
            response = client.get(
                "/api/profiles",
                headers={"Authorization": "Bearer campus-secret"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("PLUTO", response.json())

    def test_simulator_stream_reaches_websocket_as_binary_float32(self):
        coordinator = AnalyzerCoordinator()
        with TestClient(create_app(coordinator, access_token="")) as client:
            with client.websocket_connect(
                "/ws/spectrum?client_id=web-test-client"
            ) as socket:
                response = client.post(
                    "/api/acquisition/start",
                    json={
                        "client_id": "web-test-client",
                        "device_type": "SIMULATOR",
                        "center_frequency": 2.44e9,
                        "sample_rate": 2e6,
                        "span": 1e6,
                        "gain": 20,
                        "fft_size": 4096,
                    },
                )
                self.assertEqual(response.status_code, 200)

                packet = None
                for _ in range(20):
                    message = socket.receive()
                    if message.get("bytes"):
                        packet = message["bytes"]
                        break
                    if message.get("text"):
                        json.loads(message["text"])
                self.assertIsNotNone(packet)
                header, traces = unpack_spectrum_frame(packet)
                self.assertEqual(header["type"], "frame")
                self.assertEqual(header["unit"], "dBm")
                self.assertEqual(traces["amplitude"].dtype, np.dtype("float32"))
                self.assertEqual(traces["amplitude"].size, header["bins"])

                stop = client.post(
                    "/api/acquisition/stop",
                    json={"client_id": "web-test-client", "force": False},
                )
                self.assertEqual(stop.status_code, 200)

    def test_second_browser_cannot_reconfigure_without_taking_control(self):
        coordinator = AnalyzerCoordinator()
        coordinator.claim_control("first-browser")
        with self.assertRaisesRegex(Exception, "Another browser"):
            coordinator.claim_control("second-browser")
        coordinator.claim_control("second-browser", force=True)
        self.assertEqual(
            coordinator.snapshot()["controller_id"], "second-browser"
        )


if __name__ == "__main__":
    unittest.main()

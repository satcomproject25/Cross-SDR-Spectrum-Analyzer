import subprocess
import re

from .acquisition import AcquisitionError, enumerate_devices
from .models import DeviceInfo


def _load_soapy():
    try:
        import SoapySDR
    except (ImportError, OSError) as exc:
        raise AcquisitionError(
            "SoapySDR Python bindings could not be loaded. Start this program from "
            "the Radioconda Prompt and install the packages listed in INSTALL.md."
        ) from exc
    return SoapySDR


class SDR:

    def __init__(self, hackrf_info_path=None):
        self.path = hackrf_info_path

    def detect(self):

        device = DeviceInfo()

        if not self.path:
            return device

        try:

            result = subprocess.run(
                [self.path],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return device

            output = result.stdout

            if "Found HackRF" in output:
                device.connected = True
                device.device_name = "HackRF One"

            board = re.search(r"Board ID Number:\s*(.+)", output)
            if board:
                device.board_id = board.group(1).strip()

            serial = re.search(r"Serial number:\s*([A-Fa-f0-9]+)", output)
            if serial:
                device.serial_number = serial.group(1)

            firmware = re.search(r"Firmware Version:\s*(.+)", output)
            if firmware:
                device.firmware = firmware.group(1).strip()

            usb = re.search(r"USB API Version:\s*(.+)", output)
            if usb:
                device.usb_api = usb.group(1).strip()

        except Exception as e:
            print(e)

        return device

    def configure_receive(
        self,
        device_type: str,
        center_frequency: float = 100e6,
        sample_rate: float = 2e6,
        gain: float = 20.0,
        channel: int = 0,
    ) -> DeviceInfo:
        soapy = _load_soapy()
        matches = enumerate_devices(device_type)
        if not matches:
            raise AcquisitionError(
                f"No {device_type} was found by SoapySDR. Run 'SoapySDRUtil --find' to diagnose."
            )

        device_type = device_type.upper()
        driver = {
            "HACKRF": "hackrf",
            "USRP": "uhd",
            "PLUTO": "plutosdr",
        }.get(device_type)
        if driver is None:
            raise AcquisitionError(f"Unsupported SDR type: {device_type}")
        selector = f"driver={driver}"
        if device_type == "USRP" and matches[0].get("serial"):
            selector += f",serial={matches[0]['serial']}"
        elif device_type == "PLUTO":
            for key in ("uri", "serial", "hw_serial"):
                if matches[0].get(key):
                    selector += f",{key}={matches[0][key]}"
                    break
        device = soapy.Device(selector)
        direction = soapy.SOAPY_SDR_RX
        stream = None
        try:
            device.setSampleRate(direction, channel, sample_rate)
            device.setFrequency(direction, channel, center_frequency)

            if device_type == "HACKRF":
                # HackRF must use explicit stages so aggregate gain never enables AMP.
                requested_gain = 2.0 * round(min(62.0, max(0.0, gain)) / 2.0)
                device.setGain(direction, channel, "AMP", 0.0)
                device.setGain(direction, channel, "LNA", 24.0)
                device.setGain(direction, channel, "VGA", requested_gain)
            else:
                requested_gain = float(gain)
                try:
                    gain_range = device.getGainRange(direction, channel)
                    requested_gain = max(
                        float(gain_range.minimum()),
                        min(float(gain_range.maximum()), requested_gain),
                    )
                except (AttributeError, RuntimeError, TypeError):
                    pass
                device.setGain(direction, channel, requested_gain)

            actual_rate = float(device.getSampleRate(direction, channel))
            actual_frequency = float(device.getFrequency(direction, channel))
            if abs(actual_rate - sample_rate) / sample_rate > 0.01:
                raise AcquisitionError(
                    f"Device selected {actual_rate / 1e6:.3f} Msps instead of the requested "
                    f"{sample_rate / 1e6:.3f} Msps. Select a supported sample rate."
                )

            stream = device.setupStream(direction, soapy.SOAPY_SDR_CF32, [channel])

            # SoapyHackRF::activateStream() reports failure with a RETURN CODE
            # (SOAPY_SDR_STREAM_ERROR = -2), never an exception. Ignoring it leaves
            # _current_mode = HACKRF_TRANSCEIVER_MODE_OFF: the RX LED stays off and
            # nothing streams while the app reports "connected".
            rc = device.activateStream(stream)
            if rc != 0:
                detail = soapy.errToStr(rc) if hasattr(soapy, "errToStr") else str(rc)
                raise AcquisitionError(
                    f"activateStream failed ({rc}: {detail}). The device opened but "
                    "never entered RX mode."
                )
        finally:
            if stream is not None:
                try:
                    device.deactivateStream(stream)
                except Exception:
                    pass
                try:
                    device.closeStream(stream)
                except Exception:
                    pass
            try:
                soapy.Device.unmake(device)      # hackrf_close
            except Exception:
                pass

        label = matches[0].get("label") or matches[0].get("hardware") or device_type
        details = dict(matches[0])
        details["configured_center_frequency"] = str(actual_frequency)
        details["configured_sample_rate"] = str(actual_rate)
        details["configured_gain"] = str(requested_gain)

        return DeviceInfo(
            connected=True,
            device_name=label,
            driver=matches[0].get("driver", "Unknown"),
            serial_number=(
                matches[0].get("serial")
                or matches[0].get("hw_serial")
                or matches[0].get("usb,serial")
                or "Unknown"
            ),
            hardware_key=matches[0].get("type", matches[0].get("hardware", "Unknown")),
            details=details,
        )

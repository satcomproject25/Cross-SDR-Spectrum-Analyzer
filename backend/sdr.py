import subprocess
import re

from .models import DeviceInfo


class SDR:

    def __init__(self, hackrf_info_path):
        self.path = hackrf_info_path

    def detect(self):

        device = DeviceInfo()

        try:

            result = subprocess.run(
                [self.path],
                capture_output=True,
                text=True
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

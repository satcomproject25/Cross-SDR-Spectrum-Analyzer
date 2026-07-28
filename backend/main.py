"""Command-line device discovery diagnostic."""

import argparse

from .acquisition import AcquisitionError, enumerate_devices
from .sdr import SDR


def main():
    parser = argparse.ArgumentParser(description="List SDRs visible to the analyzer")
    parser.add_argument("device", choices=("HACKRF", "USRP", "PLUTO"), nargs="?")
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Configure any detected SDR for receiving",
    )
    args = parser.parse_args()
    device_types = (args.device,) if args.device else ("HACKRF", "USRP", "PLUTO")
    found = 0
    try:
        for device_type in device_types:
            devices = enumerate_devices(device_type)
            if args.configure:
                center_frequency = 2.44e9 if device_type == "PLUTO" else 100e6
                info = SDR().configure_receive(
                    device_type, center_frequency=center_frequency
                )
                print(f"{device_type}: configured for receive")
                print(f"  {info.device_name}")
                for key, value in info.details.items():
                    print(f"  {key}: {value}")
                found += 1
            else:
                print(f"{device_type}: {len(devices)} found")
                for device in devices:
                    found += 1
                    print(f"  {device.get('label', device.get('hardware', device))}")
    except AcquisitionError as exc:
        parser.error(str(exc))
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())

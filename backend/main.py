"""Command-line device discovery diagnostic."""

import argparse

from .acquisition import AcquisitionError, enumerate_devices


def main():
    parser = argparse.ArgumentParser(description="List SDRs visible to the analyzer")
    parser.add_argument("device", choices=("HACKRF", "USRP", "PLUTO"), nargs="?")
    args = parser.parse_args()
    device_types = (args.device,) if args.device else ("HACKRF", "USRP", "PLUTO")
    found = 0
    try:
        for device_type in device_types:
            devices = enumerate_devices(device_type)
            print(f"{device_type}: {len(devices)} found")
            for device in devices:
                found += 1
                print(f"  {device.get('label', device.get('hardware', device))}")
    except AcquisitionError as exc:
        parser.error(str(exc))
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())

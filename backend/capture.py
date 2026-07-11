from pathlib import Path
import subprocess

from .models import CaptureConfig


class CaptureEngine:

    def __init__(self, transfer_path, recording_directory):

        self.transfer = transfer_path

        self.recordings = Path(recording_directory)

        self.recordings.mkdir(exist_ok=True)

    def capture(self, config: CaptureConfig):

        output = self.recordings / config.filename

        command = [

            self.transfer,

            "-r", str(output),

            "-f", str(config.center_frequency),

            "-s", str(config.sample_rate),

            "-n", str(config.sample_count),

            "-l", str(config.lna_gain),

            "-g", str(config.vga_gain)

        ]

        if config.amp_enable:
            command.append("-a")
            command.append("1")
        else:
            command.append("-a")
            command.append("0")

        print("\nStarting IQ Capture...\n")

        print("\nExecuting Command:")
        print(" ".join(command))

        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        print("\nReturn Code:", result.returncode)

        print("\n----- STDOUT -----")
        print(result.stdout)

        print("\n----- STDERR -----")
        print(result.stderr)
        


        if result.returncode != 0:

            raise RuntimeError("Capture Failed")

        print("\nCapture Finished")

        return output

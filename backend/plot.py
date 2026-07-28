import matplotlib.pyplot as plt


class SpectrumPlotter:

    def plot(self, traces, power_offset_db: float | None = None):
        """Plot raw dBFS, or calibrated dBm when an offset is supplied."""

        offset = float(power_offset_db) if power_offset_db is not None else 0.0
        unit = "dBm" if power_offset_db is not None else "dBFS"

        plt.figure(figsize=(12, 6))

        plt.plot(
            traces.frequency / 1e6,
            traces.live + offset,
            label="Live",
            linewidth=1
        )

        plt.plot(
            traces.frequency / 1e6,
            traces.max_hold + offset,
            label="Max Hold",
            linewidth=1
        )

        plt.plot(
            traces.frequency / 1e6,
            traces.min_hold + offset,
            label="Min Hold",
            linewidth=1
        )

        plt.plot(
            traces.frequency / 1e6,
            traces.average + offset,
            label="Average",
            linewidth=1
        )

        plt.title("SDR Spectrum Analyzer")

        plt.xlabel("Frequency (MHz)")
        plt.ylabel(f"Amplitude ({unit})")

        plt.grid(True)

        plt.legend()

        plt.tight_layout()

        plt.show()

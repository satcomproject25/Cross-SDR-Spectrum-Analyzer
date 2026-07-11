import matplotlib.pyplot as plt


class SpectrumPlotter:

    def plot(self, traces):

        plt.figure(figsize=(12, 6))

        plt.plot(
            traces.frequency / 1e6,
            traces.live,
            label="Live",
            linewidth=1
        )

        plt.plot(
            traces.frequency / 1e6,
            traces.max_hold,
            label="Max Hold",
            linewidth=1
        )

        plt.plot(
            traces.frequency / 1e6,
            traces.min_hold,
            label="Min Hold",
            linewidth=1
        )

        plt.plot(
            traces.frequency / 1e6,
            traces.average,
            label="Average",
            linewidth=1
        )

        plt.title("SDR Spectrum Analyzer")

        plt.xlabel("Frequency (MHz)")
        plt.ylabel("Amplitude (dB)")

        plt.grid(True)

        plt.legend()

        plt.tight_layout()

        plt.show()

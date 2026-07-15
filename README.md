# SDR Frequency Analyzer

A desktop spectrum analyzer for receiving and displaying live RF signals with:

- HackRF One
- Ettus USRP devices supported by UHD
- A built-in IQ simulator for testing without hardware

The application continuously receives complex IQ samples from the selected
source, calculates an FFT, and displays a live spectrum and waterfall. Existing
analysis features include clear/write, max hold, min hold, averaging, peak
measurements, markers, delta markers, occupied bandwidth, and CSV export.
A small, slow-blinking red marker automatically follows the strongest live FFT
bin. Six normal/delta markers can be attached to CW, Max hold, Min hold, or
Average, with one trace selected for all markers at a time. Marker selection
defaults to **None** so spectrum clicks cannot create markers accidentally.

> **Current amplitude unit:** dBFS. Absolute dBm requires RF calibration for the
> specific SDR, frequency, gain, sample rate, and signal path. See
> [Amplitude: dBFS and dBm](#amplitude-dbfs-and-dbm).

## Contents

- [How the project works](#how-the-project-works)
- [Quick test without hardware](#quick-test-without-hardware)
- [Installation](#installation)
- [Running with an SDR](#running-with-an-sdr)
- [Using the interface](#using-the-interface)
- [Measurements](#measurements)
- [Amplitude: dBFS and dBm](#amplitude-dbfs-and-dbm)
- [Calibration guide](calibration.md)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [RF safety](#rf-safety)

## How the project works

The same processing pipeline is used for physical SDRs and the simulator.
Simulator mode generates IQ samples; it does not generate a ready-made graph.

```mermaid
flowchart LR
    A["HackRF / USRP / Simulator"] --> B["Complex IQ samples"]
    B --> C["4096-point Hann-windowed FFT"]
    C --> D["Frequency bins and dBFS levels"]
    D --> E["Live, max hold, min hold, average"]
    E --> F["Peaks and measurements"]
    F --> G["SpectrumFrame"]
    G --> H["Spectrum, waterfall, markers and readouts"]
```

In simple terms:

1. `backend/acquisition.py` finds the selected SDR through SoapySDR and opens a
   continuous receive stream. Simulator mode creates two nearby QPSK/OFDM-like
   occupied carriers with noise locally.
2. Acquisition runs on a background thread so the GUI stays responsive.
3. `backend/dsp.py` applies a Hann window and computes a 4096-point FFT. It
   converts FFT-bin magnitudes into dBFS and builds the frequency axis.
4. `backend/trace.py` updates the live, max-hold, min-hold, and average arrays.
5. `backend/measurements.py` and `backend/peak.py` calculate the measurement
   values. The renderer places the red auto-peak indicator on the strongest live
   FFT bin.
6. `backend/controller.py` packages everything into one `SpectrumFrame`.
7. Qt sends that frame to the spectrum renderer and waterfall in the frontend.

The default FFT size is 4096. The approximate resolution bandwidth is:

```text
RBW = sample rate / 4096
```

For example, at 20 Msps, the RBW is approximately 4.883 kHz.

## Quick test without hardware

Only Python, NumPy, PyQt6, and pyqtgraph are needed for simulator mode.

From the repository root:

```powershell
python run.py
```

Then:

1. Leave **SIMULATOR** selected.
2. Press **Run**.
3. Two nearby digital-carrier bands and a noise floor should appear.
4. Enable **Max Hold**, **Min Hold**, and **Average**. The traces should separate
   because the simulated carrier levels change over time.
5. Choose a **Trace Marker** option, then click the spectrum to place a marker.
6. Enable **Delta** and drag the delta marker. Both markers remain snapped to the
   selected trace instead of moving freely.
7. Check the waterfall, measurements, screenshot, and CSV export.
8. Change center frequency, span, sample rate, or gain. The source is restarted
   with the new settings and trace history begins again.
9. Press **Stop** when finished.

## Installation

### Required Python and GUI packages

| Package | Used for |
|---|---|
| Python 3.10 or newer | Application runtime |
| NumPy | IQ arrays, FFT, traces, and measurements |
| PyQt6 | Desktop interface and thread-safe signals |
| pyqtgraph | Spectrum, waterfall, traces, and markers |

### Required SDR packages

| Package | Used for |
|---|---|
| SoapySDR with Python bindings | Common streaming and discovery interface |
| `soapysdr-module-hackrf` and `hackrf` | HackRF One |
| `soapysdr-module-uhd` and `uhd` | Ettus USRP |

The recommended environment is Radioconda. From a Radioconda Prompt:

```powershell
mamba install -c conda-forge -c ryanvolz numpy pyqt6 pyqtgraph soapysdr soapysdr-module-hackrf soapysdr-module-uhd hackrf uhd
```

Alternatively, create the supplied environment:

```powershell
mamba env create -f environment.yml
conda activate freqanalyzer
```

`requirements.txt` contains the Python-only packages. It is not sufficient for
physical SDRs because pip does not install all native device drivers and DLLs.

For Windows driver installation, UHD image setup, PATH configuration, and
offline ISRO deployment, read [INSTALL.md](INSTALL.md).

## Running with an SDR

Always start the program from an activated **Radioconda Prompt** in the project
root:

```powershell
cd C:\path\to\freqanalyzer
python run.py
```

Do not use `py main.py`. `py` may select a different Python installation, and
the application entry point is `run.py`.

### HackRF One

Verify the device before opening the application:

```powershell
hackrf_info
SoapySDRUtil --find="driver=hackrf"
```

Then:

1. Keep the signal-generator RF output off.
2. Connect the generator to the HackRF antenna SMA through suitable attenuation.
3. Run `python run.py`.
4. Select **HackRF**.
5. Set center frequency, span, sample rate, and a moderate starting gain.
6. Press **Run** and wait for the connected status.
7. Enable the signal generator at a safe low level.

Placing a CW tone slightly away from the exact center frequency is useful
because direct-conversion SDRs can show a DC artifact at the center bin.

### Ettus USRP

Before running the GUI:

```powershell
uhd_find_devices
uhd_usrp_probe
SoapySDRUtil --find="driver=uhd"
```

Run `uhd_images_downloader` during initial setup. USB USRPs require the correct
Windows USB driver. Network USRPs must be reachable on the configured network
interface and permitted by the local firewall.

Select **Ettus USRP X301** in the application to load the X300-series profile:
up to 200 MS/s and a 160 MHz span. Ettus documents the product as X300 (the
Kintex-7 325T model); this UI uses the requested X301 label for that profile.
The full 160 MHz span requires a compatible 160 MHz daughterboard plus 10 GigE
or PCIe. A 1 GigE link is limited to substantially lower streaming rates. The
analyzer discovers and opens the USRP only when acquisition starts and uses RX
channel 0. Switching back to **HackRF One** restores its 20 MS/s and 20 MHz
limits before the next stream opens.

## Using the interface

The header is reserved for device selection and acquisition state. Tuning and
receiver configuration live in **Analyzer Setup** on the left. The right-side
**Analysis** dock separates the remaining controls into **Measure**, **Traces**,
and **Markers** tabs so the spectrum and waterfall remain the visual focus. The
three tabs always share the full Analysis width equally. Edge-arrow handles hide
or restore either side dock; with both docks hidden, the central spectrum and
waterfall expand across the complete workspace. The interface uses a true black
background with high-contrast near-black panels, gray borders, white text, and
cyan interaction accents so controls and plot annotations remain visible.

### Device and receiver controls

| Control | Meaning |
|---|---|
| Device | Select Simulator, HackRF One, or the Ettus USRP X301 profile |
| Start / Stop acquisition | Open or close the continuous receive stream |
| Center | RF center frequency in Hz, kHz, MHz, or GHz |
| Span | Width of spectrum displayed around the center |
| SR | Hardware sample rate in mega-samples per second |
| Gain | Receiver gain requested through SoapySDR |

The displayed span cannot exceed the sample rate. If a smaller span is selected,
the backend crops the FFT bins around the center frequency. Changing a receiver
setting while running performs a controlled stream restart.

Device selection updates both the sample-rate choices and the span limit. The
HackRF profile restores 20 MS/s and 20 MHz. The X301 profile exposes 200 MS/s
and 160 MHz subject to its daughterboard and host-link requirements. A device
can still reject a setting unsupported by its exact hardware configuration; the
status bar displays that error rather than silently continuing.

### Traces

| Trace | Color | Behavior |
|---|---|---|
| Clear Write | Cyan | Most recent FFT frame |
| Max Hold | Violet | Highest value reached by every frequency bin |
| Min Hold | Blue | Lowest valid displayed-sweep value reached by every frequency bin since Min Hold was enabled |
| Average | Yellow | Running linear-power average of every frequency bin, displayed in dBFS |

Max-hold and average history start with acquisition. Min hold starts fresh when
it is enabled. Trace history resets after the stream is reconfigured or
restarted. Numerical FFT-floor values are excluded from min hold so a single
underflow bin cannot pin the trace to -140 dBFS. Multiple traces can be displayed
at the same time. Average uses the same power-detector path for Simulator,
HackRF, and USRP input, so noise-like digital modulation remains visible instead
of being suppressed by direct arithmetic averaging of dB values. Hardware modes
show only carriers physically present at their RF inputs; no simulator signal is
mixed into live SDR samples.

### Markers

- **None** is selected initially. While it is active, spectrum clicks, context
  placement, and Peak Search cannot create or move a normal marker.
- Select **CW**, **Max hold**, **Min hold**, or **Average** in **Trace Marker**.
  This one selection applies to all six normal markers and their delta markers.
- Select marker M1 through M6 and click the spectrum to place it. Changing
  **Trace Marker** reattaches all existing markers at their current frequencies.
- Edit a marker's **Freq** cell in the marker table to move it precisely. A plain
  number is interpreted as MHz; explicit `Hz`, `kHz`, `MHz`, and `GHz` suffixes
  are accepted. The marker snaps to the nearest displayed FFT bin.
- A normal marker snaps to the nearest FFT bin and follows that bin's value on
  the selected trace as new frames arrive.
- Delta mode creates a second marker relative to the selected normal marker.
- The delta marker also snaps to the selected trace while being dragged.
- Delta frequency and amplitude are shown relative to the parent marker.
- **Clear All** removes all normal and delta markers.
- A small red triangle automatically tracks the global live-spectrum peak and
  blinks every 700 ms. Red is reserved for this automatic indicator.

### Waterfall

The waterfall stores recent spectrum frames as rows. Frequency runs horizontally
and older frames move through the time axis. Color represents the dBFS level.

### Screenshot and CSV

- **Screenshot** saves an image of the application.
- **Export CSV** saves frequency, live amplitude, max hold, min hold, and average
  columns when those arrays are available.
- Exports default to `SpectrumAnalyzer_Exports` in the current user's home
  directory, but the file dialog allows another location.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Space | Run or stop acquisition |
| C | Toggle clear/write |
| Ctrl+H | Toggle max hold |
| Ctrl+L | Toggle min hold |
| Ctrl+G | Toggle average |
| Shift+M | Toggle delta marker |
| S | Screenshot |
| Ctrl+E | Export CSV |
| `+` / `-` | Zoom in / out |
| R | Reset zoom |
| Escape | Stop acquisition |

Right-clicking the spectrum also provides marker placement, marker clearing,
center-here, peak search, zoom, and screenshot actions.

## Measurements

The right-side measurement panel currently reports:

| Measurement | Current calculation |
|---|---|
| Peak Frequency | Frequency of the strongest live FFT bin |
| Peak Amplitude | Amplitude of that bin in dBFS |
| Noise Floor | Median amplitude of all displayed FFT bins |
| Occupied Bandwidth | Frequency interval containing the middle 99% of displayed spectral power: 0.5% to 99.5% cumulative power |
| Channel Power | Sum of linear power from every displayed FFT bin, converted back to dBFS |

Important interpretation notes:

- Noise floor is a per-bin value and changes with sample rate, FFT size, RBW,
  window, and receiver gain.
- Occupied bandwidth includes displayed noise. A weak signal can therefore
  produce a large occupied-bandwidth value.
- Channel power currently integrates the complete displayed span; there is no
  separately selected channel boundary.
## Amplitude: dBFS and dBm

The SDR supplies normalized digital IQ values. Therefore, the backend can
directly calculate dBFS:

```text
0 dBFS = digital full scale / ADC clipping boundary
negative dBFS = below digital full scale
```

dBm is different: it is absolute RF power at a physical reference plane. Raw IQ
samples do not contain enough information to determine it universally. The
conversion changes with:

- SDR model and individual serial number
- center frequency
- receiver gain and internal gain stages
- sample rate and analog filtering
- selected RX connector and RF path
- cable and attenuator loss
- temperature and device variation

A calibrated conversion has the form:

```text
input power (dBm) = measured level (dBFS) + calibration offset (dB)
```

The offset must be measured using a known signal generator at the SDR input and
stored for the relevant frequency, gain, sample rate, and RF path. A single
fixed offset would only be an estimate and would not provide Keysight-class
accuracy. Simulator values cannot represent physical dBm because the simulator
has no RF connector.

Until calibration tables are added, changing the label from dBFS to dBm would
produce incorrect absolute readings. Frequency, bandwidth, relative level,
trace holds, averaging, and marker-delta measurements remain useful in dBFS.

## Project structure

```text
freqanalyzer/
|-- run.py                    Application entry point
|-- README.md                 Project overview and usage
|-- INSTALL.md                Detailed drivers and offline installation
|-- calibration.md            Frequency and dBFS-to-dBm calibration procedure
|-- calibration.json          Device and serial-specific calibration values
|-- environment.yml           Complete Conda environment
|-- requirements.txt          Python-only requirements
|-- backend/
|   |-- acquisition.py        SoapySDR streaming and IQ simulator
|   |-- controller.py         IQ-to-SpectrumFrame processing pipeline
|   |-- calibration.py        Calibration file loader
|   |-- dsp.py                Window, FFT, frequency axis, and dBFS
|   |-- trace.py              Live, max/min hold, and average traces
|   |-- peak.py               Peak detection
|   |-- measurements.py       Spectrum measurements
|   |-- models.py             Shared data structures
|   |-- main.py               Command-line SDR discovery diagnostic
|   |-- capture.py            Legacy HackRF file-capture helper
|   |-- iqreader.py           Legacy IQ-file reader
|   `-- plot.py               Legacy matplotlib plot helper
|-- frontend/
|   |-- gui.py                Main window, controls, status, and backend bridge
|   |-- renderer.py           Spectrum traces and marker behavior
|   |-- waterfall.py          Waterfall history display
|   |-- freq_control.py       Frequency/unit input widget
|   |-- marker_dropdown.py    M1 through M6 selector
|   `-- recorder.py           Screenshot and CSV export
`-- tests/
    |-- test_acquisition.py    Mock SDR and live simulator tests
    |-- test_gui.py            Device profiles and tabbed UI tests
    |-- test_pipeline.py       DSP, tone, span, hold, and average tests
    `-- test_renderer.py       Auto-peak and multi-trace marker tests
```

`backend/main.py` is a discovery diagnostic, not the graphical application.
Run the graphical analyzer with `python run.py`.

## Testing

Run the automated tests without SDR hardware:

```powershell
python -m unittest discover -s tests -v
```

The tests verify:

- tone frequency and dBFS level
- max hold, min hold, and average accumulation
- display-span cropping and finite measurements
- mocked SoapySDR stream delivery and shutdown
- isolated HackRF/USRP selection and mocked USRP receive configuration
- X300-series/HackRF profile limits and marker-disabled UI state
- real-time simulator delivery through the normal analyzer pipeline

Run a syntax check with:

```powershell
python -m compileall backend frontend tests run.py
```

Passing software tests cannot prove USB drivers, RF input safety, device-specific
sample rates, or measurement calibration. Perform final acceptance with the
actual SDR and a safely attenuated known signal source.

## Troubleshooting

### The GUI opens but shows the simulator

Simulator is the default device. Select **HackRF** or **USRP**, then
press **Run**.

### SoapySDR cannot be imported

Launch the program from a Radioconda Prompt and check:

```powershell
SoapySDRUtil --info
```

If Python or vendor executables are taken from another installation, correct
`PATH` so Radioconda's executables and DLLs are used together.

### No HackRF is detected

```powershell
hackrf_info
SoapySDRUtil --find="driver=hackrf"
```

Check the USB cable, Windows Device Manager, and WinUSB driver.

### No USRP is detected

```powershell
uhd_find_devices
uhd_usrp_probe
SoapySDRUtil --find="driver=uhd"
```

Check UHD images, USB drivers, or the network interface/subnet as appropriate.

### A large spike appears at the center

This can be a normal DC-offset artifact of a direct-conversion receiver. Test a
signal generator slightly away from the exact center frequency.

### The signal is missing or distorted

- Confirm center frequency and span include the source.
- Confirm the signal generator output is enabled.
- Check cables, connectors, and attenuation.
- Start with moderate receiver gain and adjust gradually.
- Excessive gain can create clipping, intermodulation products, and a raised
  noise floor.
- Never solve a weak display by applying unsafe RF power to the SDR input.

## RF safety

Use a known external attenuator between a signal generator and every SDR until
the complete RF level is understood. Check the manual for the exact SDR,
daughterboard, selected connector, and hardware revision.

For HackRF One, the documented maximum input is **-5 dBm**. Exceeding it can
permanently damage the receiver. Begin well below that level at the HackRF
connector and increase only when necessary.

Also verify that the cable uses the correct SMA connector and that the signal is
connected to the RF/antenna input—not a clock, trigger, or output connector.

## Current scope and limitations

- Receive-only spectrum analysis; the application does not transmit.
- One SDR and receive channel 0 at a time.
- Maximum GUI sample-rate selection is currently 20 Msps.
- FFT size is fixed at 4096.
- Span is limited to the selected sample rate; wide sweeps across multiple LO
  tunings are not implemented.
- Amplitude is dBFS until device-specific RF calibration is implemented.
- Channel power integrates the full displayed span.
- This is an SDR-based analyzer, not a replacement for a calibrated laboratory
  spectrum analyzer or power meter.

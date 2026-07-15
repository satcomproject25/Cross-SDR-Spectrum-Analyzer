# Installation and hardware setup

The analyzer uses SoapySDR as a common streaming layer for HackRF One and
Ettus USRP. Start it from a **Radioconda Prompt** so the
SoapySDR DLLs and device modules are already on `PATH`.

## Required libraries

| Library/package | Purpose |
|---|---|
| Python 3.10 or newer | Application runtime |
| NumPy | IQ arrays, FFT, holds, averages, and measurements |
| PyQt6 | Desktop GUI and thread-safe frame signals |
| pyqtgraph | Spectrum, traces, markers, and waterfall |
| SoapySDR (including Python bindings) | Common device discovery and RX streaming API |
| soapysdr-module-hackrf + hackrf | HackRF One driver and diagnostic tools |
| soapysdr-module-uhd + uhd | Ettus USRP driver, utilities, firmware, and FPGA support |

The program itself does not require GNU Radio, SciPy, pandas, matplotlib,
or vendor-specific Python APIs such as `uhd` or `pyadi-iio`.

### Connected installation

Radioconda already includes the SDR packages above. Install the GUI packages
and make sure all required packages are present:

```powershell
mamba install -c conda-forge -c ryanvolz numpy pyqt6 pyqtgraph soapysdr soapysdr-module-hackrf soapysdr-module-uhd hackrf uhd
```

Alternatively, create an isolated environment from the supplied file:

```powershell
mamba env create -f environment.yml
conda activate freqanalyzer
```

For an offline ISRO system, download/cache the exact Conda packages and all
transitive dependencies on a connected computer with the same OS and CPU.
Transfer that package cache or a packed environment through the approved media
process. Do not rely only on `requirements.txt`: pip cannot provide the native
SoapySDR device modules and vendor libraries.

## Windows device preparation

1. HackRF One: install the WinUSB driver (Radioconda recommends Zadig), then verify:

   ```powershell
   hackrf_info
   SoapySDRUtil --find="driver=hackrf"
   ```

2. Ettus USRP: install the appropriate UHD USB driver for USB/B-series devices.
   Download the firmware/FPGA image set once while connected, or transfer the
   resulting UHD images directory to the offline machine:

   ```powershell
   uhd_images_downloader
   uhd_find_devices
   uhd_usrp_probe
   SoapySDRUtil --find="driver=uhd"
   ```

   Network USRPs must be on a reachable interface/subnet and allowed by the local
   firewall. UHD selects the correct transport from device discovery.

Finally verify that both modules load:

```powershell
SoapySDRUtil --info
SoapySDRUtil --find
python -m backend.main
```

If the vendor `.exe` files were installed outside Radioconda, add their `bin`
directories to `PATH` **before** launching the Radioconda Prompt/application.
The analyzer streams through the matching DLLs/modules; merely finding an `.exe`
is not sufficient if the corresponding Soapy module cannot load.

## Run

From the repository root in the activated Radioconda environment:

```powershell
python run.py
```

Select the device type, center frequency, span, sample rate, and gain, then press
**Start acquisition**. Parameter changes while running trigger a controlled
device restart. The HackRF One profile is capped at 20 MS/s and 20 MHz. The
Ettus USRP X301 profile uses the X300-series ceilings of 200 MS/s and 160 MHz;
the widest mode requires a 160 MHz daughterboard and 10 GigE or PCIe.
Trace holds and averaging reset when the stream is started or reconfigured.

### Test without an SDR

1. Start the application with `python run.py`.
2. Select **Simulator** (it is selected by default) and press **Start acquisition**.
3. Two nearby QPSK/OFDM-like occupied carriers with noise will appear around the
   selected center frequency. Their symbols and levels change continuously.
4. Enable **Max Hold**, **Min Hold**, and **Average** individually or together.
   The violet and blue envelopes should separate while the yellow power average
   settles into two stable digital-carrier shapes.
5. Confirm **None** prevents click placement, then choose Marker 1/2/3 and each
   **Trace Marker** option, enable delta mode,
   inspect the waterfall, change center/span/sample rate, and export a CSV or
   screenshot. The small blinking red triangle should follow the global peak.
6. Press **Stop acquisition**. No SoapySDR installation or device driver is required for
   simulator mode; only NumPy, PyQt6, and pyqtgraph are needed.

This mode generates complex IQ blocks and sends them through the same
`AnalyzerPipeline` used by physical SDRs. It does not bypass the FFT or create
display-ready spectrum arrays, so it is suitable for end-to-end GUI testing.

## RF safety and amplitude units

Use attenuation between a signal generator and the SDR. Never assume a common
safe input level across HackRF and USRP daughterboards; check the manual
for the exact hardware and start at a low generator level.

Displayed amplitude is **dBFS**, because raw SDR samples are not factory-calibrated
to connector power. Frequency, span, RBW, relative amplitude, max/min hold,
averaging, markers, and delta markers remain valid. Absolute dBm accuracy would
require a separate calibration for each device, gain, frequency, and signal path.

## Offline acceptance check

The automated DSP, acquisition, and simulator behavior can be tested without hardware:

```powershell
python -m unittest discover -s tests -v
```

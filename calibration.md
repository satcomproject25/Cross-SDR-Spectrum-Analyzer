# Frequency and amplitude calibration

This guide explains how to verify the analyzer with a known signal generator.
Calibration is specific to the SDR, its serial number, frequency, sample rate,
gain settings, cable, attenuation, and temperature. It does not turn an SDR into
a traceable spectrum analyzer unless the generator, attenuators, and procedure
are themselves traceable and their uncertainties are included.

## 1. What caused the apparent 22 kHz frequency error

The application tunes HackRF in `HackRFAcquisition._open_locked()` in
`backend/acquisition.py`:

```python
device.setFrequency(SOAPY_SDR_RX, channel, requested_frequency)
driver_frequency = device.getFrequency(SOAPY_SDR_RX, channel)
```

That readback was already being copied into `AcquisitionConfig`, then into
`IQFrame.center_frequency` in `backend/controller.py`, and finally into the FFT
axis in `backend/dsp.py`.

The important limitation is in SoapyHackRF itself: its `setFrequency()` stores
the requested number in an internal stream field, and `getFrequency()` returns
that stored number. It is not a measurement of the physical LO or reference
oscillator. Therefore, adding another `getFrequency()` call cannot reveal the
true RF center.

The application keeps three quantities separate:

1. requested tuning frequency: sent to the hardware;
2. driver frequency: the value returned by SoapySDR;
3. calibrated display center: `driver_frequency - frequency_error_hz`.

`backend/acquisition.py` applies the correction only to the displayed frequency
axis; it does not retune the HackRF. New HackRF entries use a fixed error plus a
proportional oscillator term:

```json
"frequency_fixed_error_hz": -297.7,
"frequency_ppm_error": 8.9304
```

The sign convention is `observed error = displayed - reference`: a positive
error means the display is high, so it is subtracted. Existing entries that only
contain `frequency_axis_offset_hz` remain supported for compatibility.

## 2. Frequency calibration procedure

### Equipment and setup

- Use a signal generator with a known frequency accuracy substantially better
  than the SDR being tested.
- Lock the generator and SDR to the same 10 MHz reference when the hardware
  supports it. HackRF One normally uses its onboard reference unless an
  appropriate external clock arrangement is provided.
- Put a known attenuator between the generator and SDR. Never exceed the SDR's
  safe input level.
- Let the generator and SDR warm up for at least 15 to 30 minutes.
- Keep sample rate, gain, USB setup, and temperature unchanged during a run.
- Place the test tone away from the exact center bin because the DSP subtracts
  the IQ mean and direct-conversion receivers have a DC artifact at center.

### Measurements

1. Temporarily set the applicable frequency-calibration values to `0.0` in
   `calibration.json`.
2. Select HackRF, choose a sample rate, and use the smallest practical span.
3. Set the generator to a known frequency inside that span, preferably 100 to
   300 kHz away from center.
4. Record the known generator frequency and the marker frequency reported by
   the application after the trace settles.
5. Calculate:

   ```text
   observed_error_hz = displayed_frequency_hz - known_frequency_hz
   required_axis_offset_hz = known_frequency_hz - displayed_frequency_hz
   ```

6. Repeat at several widely separated RF frequencies. Using only 2440 and
   2441 MHz is not sufficient to distinguish a constant offset from ppm error.
   Include points hundreds of MHz or several GHz apart when the hardware permits.
7. Use the same FFT size but reduce the sample rate/span if possible. With the
   current 4096-point FFT, one bin is `sample_rate / 4096`; a 20 Msps setting has
   approximately 4.883 kHz bins and can hide changes of several kHz.

### Fixed offset versus oscillator ppm error

For each test point calculate `observed_error_hz`.

- Fixed software/axis offset: approximately the same error in hertz at every RF
  frequency.
- Oscillator error: error magnitude grows approximately in proportion to RF
  frequency.

The oscillator estimate is:

```text
ppm = observed_error_hz / known_frequency_hz * 1,000,000
```

For example, 22 kHz at 2.44 GHz is about 9.0 ppm. A true 9 ppm error would be
about 18 kHz at 2.0 GHz, not 22 kHz. Because FFT bins are discrete, interpolate
the peak or repeat at a lower sample rate before declaring the difference fixed.

For the most reliable result, fit all measurements to:

```text
observed_error_hz = fixed_error_hz + ppm * known_frequency_hz / 1,000,000
```

The intercept estimates a fixed offset; the slope estimates ppm. The current
implementation applies both terms to the HackRF display axis. Do not hide a
genuine clock error with one fixed number across a wide tuning range. Correct
the reference clock when possible and verify the fitted ppm term against fresh
measurements.

### Store the result

For one HackRF, place the correction under its serial number so another board is
not given the same calibration:

```json
{
  "devices": {
    "HACKRF": {
      "default": {
        "frequency_fixed_error_hz": 0.0,
        "frequency_ppm_error": 0.0,
        "power_offset_db": null
      },
      "serials": {
        "YOUR_SERIAL": {
          "frequency_fixed_error_hz": -297.7,
          "frequency_ppm_error": 8.9304,
          "power_offset_db": null
        }
      }
    }
  }
}
```

Restart acquisition after editing the file. The optional environment variable
`FREQANALYZER_CALIBRATION` can point to an approved calibration file stored
outside the repository.

## 3. Calibrating dBFS to dBm

### Why an offset is required

The SDR returns normalized complex samples. `backend/dsp.py` applies a Hann
window and reports a coherent tone amplitude as dBFS. dBFS is relative to ADC
full scale; dBm is RF power at a defined physical reference plane.

For a fixed configuration, the first-order conversion is:

```text
input_power_dbm = measured_tone_dbfs + power_offset_db
power_offset_db = known_input_power_dbm - measured_tone_dbfs
```

There is no universal HackRF, USRP, or Pluto offset. Receiver gain, frequency, filters,
sample rate, selected connector, cable loss, attenuator error, and individual
hardware all change it.

### Supported power-calibration entries

The resolver accepts these schemas, in precedence order. Device `default`
values are merged with a matching serial override before resolution.

| Entry | Resolved offset |
|---|---|
| `power_vga_table` | Directly interpolates `offset_db` by live VGA gain. |
| `power_base_offset_table` | Interpolates `base_offset_db` by center frequency, then subtracts live VGA gain. |
| `power_base_offset_db` | Subtracts live VGA gain from one base offset. |
| `power_offset_db` | Uses a legacy pre-resolved constant. |

Use arrays of objects for the two table forms:

```json
"power_base_offset_table": [
  {"freq_hz": 100000000, "base_offset_db": -11.6},
  {"freq_hz": 1000000000, "base_offset_db": -13.3}
]
```

```json
"power_vga_table": [
  {"vga_db": 20, "offset_db": -33.0},
  {"vga_db": 40, "offset_db": -53.0}
]
```

Interpolation is linear and clamps at the first or last measured point; it does
not extrapolate a new slope. `power_cal_vga_min_db` and
`power_cal_vga_max_db` can reject unmeasured gain settings. For HackRF, set
`power_cal_lna_db` and `power_cal_amp_db` to the gain-chain values used while
measuring; the application declines calibration if its fixed LNA/AMP setup does
not match. `power_cal_sample_rate_hz`, pad loss, notes, and instrument details
are useful provenance but are not currently enforced automatically.

### Tone calibration steps

1. Choose the reference plane, normally the SDR input connector.
2. Determine actual power at that plane:

   ```text
   input_dbm = generator_setting_dbm - cable_loss_db - attenuator_loss_db
   ```

   Include directional coupler or splitter loss when used.
3. Fix SDR model/serial, center frequency, sample rate, gain stages, bandwidth,
   antenna port, and reference clock. For HackRF, record the fixed LNA/AMP
   setup and each VGA setting. Record every setting.
4. Put the CW tone on an FFT bin if practical and away from DC and band edges.
5. Start at a safely low level. Confirm that the ADC and RF front end are not
   clipping and that the tone is well above the noise floor.
6. Average the marker reading over many frames. Calculate `power_offset_db`.
7. Repeat at several input powers, for example -70, -60, -50, and -40 dBm when
   safe for the exact hardware.
8. Verify that a 10 dB generator change produces approximately a 10 dB dBFS
   change. If it does, average the calculated offsets. If it does not, the path
   may be compressed, too close to the noise floor, using AGC, or otherwise
   nonlinear; do not use a single offset there.
9. Repeat across frequency and for every gain/sample-rate configuration that
   will be used. Interpolate only between measured calibration points.

If a linear fit is needed, use:

```text
input_power_dbm = slope * measured_dbfs + intercept
```

The expected slope is close to 1. A materially different slope is a warning to
investigate the measurement setup rather than blindly applying it.

### Tone level versus integrated channel power

Calibrate like with like. A peak-bin CW measurement and integrated channel
power are not interchangeable. Noise and modulated-signal power depend on FFT
window equivalent-noise bandwidth, number of integrated bins, RBW, and detector
behavior. Create a separate calibration/verification for channel power using a
known modulated source or calibrated noise source. The current channel-power
calculation sums the displayed FFT bins, so its calibration is valid only for
the same span, sample rate, FFT size, and window.

## 4. How the application applies power calibration

The power display path is implemented as follows:

1. `backend/acquisition.py` loads and merges the device/default and serial
   calibration, then resolves the live offset using frequency and gain where the
   schema requires it.
2. `backend/controller.py` keeps every trace in raw dBFS and attaches the
   resolved conversion to the frame as `power_offset_db`, `power_calibrated`,
   and `power_in_cal_range`. `backend/models.py` carries them alongside the raw
   arrays so the measurement and the calibration applied to it stay separable
   and auditable all the way out to the CSV.
3. `frontend/units.py` resolves the **operator-selected** unit against each
   frame's calibration state, and is the only place in the application allowed
   to decide that a value may be labelled dBm. The rule it enforces: a value is
   labelled `dBm` **if and only if** a valid offset was actually added to it.
4. Every display surface - spectrum, waterfall, reference level,
   peak/noise/channel-power readouts, markers, delta absolute levels, carrier
   table, status peak, and the browser console - takes its unit and offset from
   that single resolution, so they cannot disagree with one another.
5. Selecting dBm without a valid calibration does **not** produce dBm. The
   readouts stay in dBFS, the unit switch turns amber, and the operator is told
   the measurements are not calibrated yet. A missing, `null`, non-numeric,
   `NaN`, or infinite offset all take this path, as does a gain outside
   `power_cal_vga_min_db` / `power_cal_vga_max_db`.
6. A centre frequency outside the measured calibration span displays as `dBm*`
   with a warning: the offset there is a clamped endpoint value, not an
   interpolated one.
7. `webapp/protocol.py` transmits raw dBFS with the calibration metadata in the
   frame header; the browser applies the offset once, on receipt. Shifting
   server-side previously produced dBm carrier values under a dBFS column
   header.
8. `frontend/recorder.py` exports `*_dbfs` and, when available, `*_dbm` columns
   independently of the switch, plus a `#` provenance preamble.
9. Automated tests (`tests/test_units.py`) cover every row of the resolution
   table above, including each class of invalid offset.

The built-in simulator has a nominal `0.0` offset so the calibrated display path
can be tested without hardware. Its values are not physical connector power.

Do not merely rename dBFS labels to dBm. Calibration metadata should include the
SDR serial, timestamp, generator/attenuator identifiers, uncertainty, frequency,
sample rate, gain stages, bandwidth, and temperature.

## 5. Verification after any calibration change

1. Restart the acquisition so the calibration file is reloaded.
2. Test at frequencies and powers used to create the calibration.
3. Test additional points between them and at the intended operating extremes.
4. Verify HackRF, USRP, and Pluto separately; never reuse one device's values for another.
5. Save the raw CSV, generator settings, cable/attenuator data, and software
   commit alongside the calibration record.
6. Recalibrate after hardware repair, firmware/driver changes, RF-path changes,
   or any unexplained shift in frequency or amplitude.
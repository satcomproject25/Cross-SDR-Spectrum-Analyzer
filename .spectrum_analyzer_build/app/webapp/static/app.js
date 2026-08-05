(() => {
  "use strict";

  // A missing element used to return null, so one stale markup/script pairing
  // threw inside wireControls() and aborted initialize() before it ever
  // reached /api/profiles or the WebSocket. The stub keeps the rest of the
  // interface alive and the audit reports exactly what is missing.
  const missingElements = new Set();
  const elementStub = () => {
    const node = document.createElement("span");
    node.style.display = "none";
    return node;
  };
  const $ = (id) => {
    const node = document.getElementById(id);
    if (node) return node;
    missingElements.add(id);
    return elementStub();
  };

  function auditElements() {
    if (!missingElements.size) return;
    const ids = Array.from(missingElements).join(", ");
    console.error(
      `[analyzer] index.html is missing ${missingElements.size} element(s) `
      + `expected by app.js: ${ids}. The browser is probably serving a cached `
      + "app.js or index.html \u2014 hard-reload (Ctrl+Shift+R).",
    );
    toast(`Interface files are out of date (${missingElements.size} missing element(s)) \u2014 hard-reload the page`, "error");
  }
  const encoder = new TextDecoder();
  const clientId = localStorage.getItem("rf-analyzer-client-id")
    || (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
  localStorage.setItem("rf-analyzer-client-id", clientId);

  const state = {
    token: sessionStorage.getItem("rf-analyzer-token") || "",
    profiles: {},
    server: null,
    socket: null,
    reconnectTimer: null,
    latestFrame: null,
    frameSequence: 0,
    renderedSequence: -1,
    running: false,
    unit: "dBm",
    reference: 0,
    yRange: 120,
    viewStart: null,
    viewStop: null,
    carriersVisible: true,
    carriers: [],
    carrierUnit: "dBFS",
    selectedCarrier: null,
    lastCarrierPaint: 0,
    autoPeakVisible: true,
    lastPeakBlink: 0,
    logging: false,
    logRows: [],
    logIntervalMs: 1000,
    logColumns: [],
    logUnit: "dBFS",
    watchList: [],
    watchSequence: 1,
    watchTrace: "average",
    watchAperture: 5,
    lastWatchPaint: 0,
    logNextDue: 0,
    logStartedAt: 0,
    activeMarker: 0,
    markerTrace: "amplitude",
    markers: new Map(),
    pointer: null,
    dragging: null,
    receivedThisSecond: 0,
    fps: 0,
    lastFpsTick: performance.now(),
    lastConfigSignature: "",
    configTimer: null,
  };

  const TRACE_COLORS = {
    amplitude: "#37d7f2",
    max_hold: "#b785ff",
    min_hold: "#5b9dff",
    average: "#ffd65b",
  };
  const MARKER_COLORS = ["", "#54e6ff", "#ffcb54", "#8fe388", "#d997ff", "#ff8b70", "#78a8ff"];

  const spectrum = $("spectrumCanvas");
  const spectrumCtx = spectrum.getContext("2d", { alpha: false });
  const waterfall = $("waterfallCanvas");
  const waterfallCtx = waterfall.getContext("2d", { alpha: false });

  function authHeaders(json = false) {
    const headers = {};
    if (json) headers["Content-Type"] = "application/json";
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    return headers;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { ...authHeaders(Boolean(options.body)), ...(options.headers || {}) },
    });
    if (response.status === 401) {
      showTokenDialog();
      throw new Error("Access token required");
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload.detail || `Request failed (${response.status})`;
      if (response.status === 409) {
        // refresh lease ownership from the authoritative snapshot
        fetch(`/api/state?client_id=${encodeURIComponent(clientId)}`, { headers: authHeaders() })
          .then((r) => r.json())
          .then(handleServerState)
          .catch(() => {});
      }
      throw new Error(message);
    }
    return payload;
  }

  function toast(message, kind = "") {
    const item = document.createElement("div");
    item.className = `toast ${kind}`;
    item.textContent = message;
    $("toastRegion").append(item);
    setTimeout(() => item.remove(), 4200);
  }

  function showTokenDialog(error = false) {
    $("tokenDialog").hidden = false;
    $("tokenError").hidden = !error;
    setTimeout(() => $("tokenInput").focus(), 0);
  }

  function hideTokenDialog() {
    $("tokenDialog").hidden = true;
    $("tokenError").hidden = true;
  }

  function formatFrequency(value, decimals = 4) {
    const abs = Math.abs(value);
    if (abs >= 1e9) return `${(value / 1e9).toFixed(decimals)} GHz`;
    if (abs >= 1e6) return `${(value / 1e6).toFixed(decimals)} MHz`;
    if (abs >= 1e3) return `${(value / 1e3).toFixed(decimals)} kHz`;
    return `${value.toFixed(decimals)} Hz`;
  }

  function formatCompactFrequency(value) {
    const abs = Math.abs(value);
    if (abs >= 1e9) return `${(value / 1e9).toFixed(3)}G`;
    if (abs >= 1e6) return `${(value / 1e6).toFixed(3)}M`;
    if (abs >= 1e3) return `${(value / 1e3).toFixed(2)}k`;
    return value.toFixed(0);
  }

  function updateFrequencySummary() {
    const center = Number($("centerInput").value) * Number($("centerUnit").value);
    const span = Number($("spanInput").value) * 1e6;
    $("startFrequency").textContent = formatFrequency(center - span / 2, 3);
    $("stopFrequency").textContent = formatFrequency(center + span / 2, 3);
  }

  function populateProfiles() {
    const select = $("deviceSelect");
    select.replaceChildren();
    for (const [key, profile] of Object.entries(state.profiles)) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = profile.label;
      select.append(option);
    }
    select.value = "SIMULATOR";
    applyProfile("SIMULATOR", true);
  }

  function applyProfile(deviceType, resetValues) {
    const profile = state.profiles[deviceType];
    if (!profile) return;
    const sampleSelect = $("sampleRateSelect");
    const oldRate = sampleSelect.value;
    sampleSelect.replaceChildren();
    for (const rate of profile.sample_rates) {
      const option = document.createElement("option");
      option.value = rate;
      option.textContent = rate;
      sampleSelect.append(option);
    }
    sampleSelect.value = resetValues ? profile.sample_rate : oldRate;
    if (!sampleSelect.value) sampleSelect.value = profile.sample_rate;
    $("gainInput").max = String(profile.max_gain_db);
    if (Number($("gainInput").value) > profile.max_gain_db) {
      $("gainInput").value = String(profile.max_gain_db);
    }
    $("gainOutput").value = `${$("gainInput").value} dB`;
    $("profileBadge").textContent = profile.summary;
    $("profileDetail").textContent = profile.detail;
    if (resetValues) {
      $("spanInput").value = String(profile.span_hz / 1e6);
      if (deviceType === "PLUTO") $("centerInput").value = "2440";
    }
    const maxSpan = Math.min(profile.max_span_hz, Number(sampleSelect.value) * 1e6) / 1e6;
    $("spanInput").max = String(maxSpan);
    if (Number($("spanInput").value) > maxSpan) $("spanInput").value = String(maxSpan);
    updateFrequencySummary();
  }

  function collectConfig() {
    return {
      client_id: clientId,
      device_type: $("deviceSelect").value,
      center_frequency: Number($("centerInput").value) * Number($("centerUnit").value),
      sample_rate: Number($("sampleRateSelect").value) * 1e6,
      span: Number($("spanInput").value) * 1e6,
      gain: Number($("gainInput").value),
      fft_size: 4096,
    };
  }

  function scheduleReconfigure() {
    updateFrequencySummary();
    if (!state.running) return;
    clearTimeout(state.configTimer);
    state.configTimer = setTimeout(() => startAcquisition(true), 280);
  }

  async function startAcquisition(reconfigure = false) {
    try {
      const config = collectConfig();
      const signature = JSON.stringify(config);
      if (reconfigure && signature === state.lastConfigSignature) return;
      state.lastConfigSignature = signature;
      await api("/api/acquisition/start", {
        method: "POST",
        body: JSON.stringify(config),
      });
      state.running = true;
      updateRunButton();
      if (!reconfigure) toast(`Starting ${state.profiles[config.device_type].label}`);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function stopAcquisition() {
    try {
      await api("/api/acquisition/stop", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, force: false }),
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function updateRunButton() {
    $("runButton").classList.toggle("running", state.running);
    $("runLabel").textContent = state.running ? "Stop acquisition" : "Start acquisition";
  }

  async function toggleRun() {
    if (state.running) await stopAcquisition();
    else await startAcquisition();
  }

  async function claimControl(force = true) {
    try {
      const snapshot = await api("/api/control/claim", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, force }),
      });
      handleServerState(snapshot);
      toast("This browser now controls the analyzer");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function handleServerState(message) {
    state.server = message;
    state.running = Boolean(message.running);
    updateRunButton();
    const status = message.status || "Idle";
    $("deviceStatus").textContent = `Device: ${status}`;
    $("deviceDot").className = `status-dot ${message.error ? "error" : state.running ? "online" : ""}`;
    $("viewerCount").textContent = String(message.viewer_count ?? 1);
    const ownsControl = !message.controller_id || message.controller_id === clientId;
    $("controlButton").textContent = ownsControl ? "In control" : "Take control";
    $("controlButton").classList.toggle("active", ownsControl);
    if (message.config && !state.latestFrame) {
      $("stageDevice").textContent = state.profiles[message.config.device_type]?.label || message.config.device_type;
    }
    if (message.error) toast(message.error, "error");
  }

  function connectWebSocket() {
    clearTimeout(state.reconnectTimer);
    if (state.socket) {
      state.socket.onclose = null;
      state.socket.close();
    }
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const query = new URLSearchParams({ client_id: clientId });
    if (state.token) query.set("token", state.token);
    const socket = new WebSocket(`${protocol}://${location.host}/ws/spectrum?${query}`);
    state.socket = socket;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      $("networkDot").className = "status-dot online";
      $("networkLabel").textContent = "Online";
    };
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data);
        if (message.type === "state") handleServerState(message);
        return;
      }
      decodeFrame(event.data);
    };
    socket.onerror = () => socket.close();
    socket.onclose = (event) => {
      $("networkDot").className = `status-dot ${event.code === 4401 ? "error" : "warning"}`;
      $("networkLabel").textContent = event.code === 4401 ? "Locked" : "Reconnecting";
      if (event.code === 4401) showTokenDialog(true);
      else state.reconnectTimer = setTimeout(connectWebSocket, 1500);
    };
  }

  function decodeFrame(buffer) {
    const view = new DataView(buffer);
    if (view.byteLength < 4) return;
    const headerLength = view.getUint32(0, true);
    const headerEnd = 4 + headerLength;
    if (headerEnd > view.byteLength) return;
    const header = JSON.parse(encoder.decode(new Uint8Array(buffer, 4, headerLength)));
    const traceBytes = buffer.slice(headerEnd);
    const traces = {};
    let offset = 0;
    for (const name of header.traces) {
      traces[name] = new Float32Array(traceBytes, offset, header.bins);
      offset += header.bins * 4;
    }
    const previous = state.latestFrame;
    state.latestFrame = { header, traces };
    state.frameSequence += 1;
    state.receivedThisSecond += 1;
    state.unit = header.unit;
    if (
      !previous
      || previous.header.frequency_start !== header.frequency_start
      || previous.header.frequency_step !== header.frequency_step
      || previous.header.bins !== header.bins
    ) {
      resetView();
      clearWaterfall();
    }
    updateMeasurements(header, traces);
    updateCarriers(header);
    sampleAmplitudeLog(header, traces);
    $("emptyState").hidden = true;
  }

  function resetView() {
    if (!state.latestFrame) return;
    const { header } = state.latestFrame;
    state.viewStart = header.frequency_start;
    state.viewStop = header.frequency_start + header.frequency_step * (header.bins - 1);
  }

  function updateMeasurements(header, traces) {
    const peaks = header.peaks || [];
    let peak = peaks[0];
    if (!peak && traces.amplitude.length) {
      let index = 0;
      for (let i = 1; i < traces.amplitude.length; i += 1) {
        if (traces.amplitude[i] > traces.amplitude[index]) index = i;
      }
      peak = {
        frequency: header.frequency_start + header.frequency_step * index,
        amplitude: traces.amplitude[index],
        bin: index,
      };
    }
    const unit = header.unit;
    if (peak) {
      $("peakAmplitude").textContent = `${peak.amplitude.toFixed(2)} ${unit}`;
      $("peakFrequency").textContent = formatFrequency(peak.frequency, 6);
      $("peakStatus").textContent = `Peak: ${peak.amplitude.toFixed(2)} ${unit}`;
    }
    $("noiseFloor").textContent = `${header.noise_floor.toFixed(2)} ${unit}`;
    $("occupiedBandwidth").textContent = formatFrequency(header.bandwidth, 3);
    $("channelPower").textContent = `${header.channel_power.toFixed(2)} ${unit}`;
    $("rbwValue").textContent = formatFrequency(header.rbw, 3);
    $("carrierCount").textContent = String((header.carriers || []).length);
    $("carrierPowerHeader").textContent = `Power (${unit})`;
    $("calibrationStatus").textContent = header.power_calibrated ? "Calibrated dBm" : "Raw dBFS";
    $("calibrationStatus").className = header.power_calibrated ? "good" : "warn";
    $("referenceUnit").textContent = unit;
    $("scaleMax").textContent = `${state.reference} ${unit}`;
    $("scaleMid").textContent = String(state.reference - state.yRange / 2);
    $("scaleMin").textContent = String(state.reference - state.yRange);
    $("stageDevice").textContent = header.device_name || "Spectrum stream";
    $("frameMeta").textContent = `${header.fft_size} FFT · ${formatFrequency(header.rbw, 3)} RBW`;
    $("fftStatus").textContent = `FFT: ${header.fft_size}`;
    $("latencyStatus").textContent = `Stream: ${Math.max(0, Date.now() - header.timestamp * 1000).toFixed(0)} ms`;
  }

  function fitCanvas(canvas, context) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
    const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      return true;
    }
    return false;
  }

  function plotGeometry() {
    return {
      left: 57,
      top: 10,
      right: spectrum.clientWidth - 11,
      bottom: spectrum.clientHeight - 26,
      width: Math.max(1, spectrum.clientWidth - 68),
      height: Math.max(1, spectrum.clientHeight - 36),
    };
  }

  function frequencyToX(frequency, geometry) {
    return geometry.left + (frequency - state.viewStart) / (state.viewStop - state.viewStart) * geometry.width;
  }

  function amplitudeToY(amplitude, geometry) {
    return geometry.top + (state.reference - amplitude) / state.yRange * geometry.height;
  }

  function xToFrequency(x, geometry) {
    return state.viewStart + (x - geometry.left) / geometry.width * (state.viewStop - state.viewStart);
  }

  function traceIndexAtFrequency(frequency, header) {
    return Math.max(0, Math.min(header.bins - 1, Math.round(
      (frequency - header.frequency_start) / header.frequency_step
    )));
  }

  function drawSpectrum() {
    fitCanvas(spectrum, spectrumCtx);
    const width = spectrum.clientWidth;
    const height = spectrum.clientHeight;
    spectrumCtx.fillStyle = "#000";
    spectrumCtx.fillRect(0, 0, width, height);
    const frame = state.latestFrame;
    const g = plotGeometry();
    drawGrid(g);
    if (!frame) return;
    if (state.viewStart == null) resetView();

    const { header, traces } = frame;
    const startIndex = traceIndexAtFrequency(state.viewStart, header);
    const stopIndex = traceIndexAtFrequency(state.viewStop, header);
    if (state.carriersVisible) drawCarriers(g, header);

    const enabled = [
      ["average", $("traceAverage").checked],
      ["min_hold", $("traceMin").checked],
      ["max_hold", $("traceMax").checked],
      ["amplitude", $("traceLive").checked],
    ];
    for (const [name, visible] of enabled) {
      if (visible) drawTrace(g, header, traces[name], name, startIndex, stopIndex);
    }
    drawWatchLines(g, header);
    drawAutoPeak(g, header, traces[state.markerTrace] || traces.amplitude, startIndex, stopIndex);
    drawMarkers(g, header, traces);
  }

  function drawGrid(g) {
    spectrumCtx.save();
    spectrumCtx.strokeStyle = "#1b2025";
    spectrumCtx.lineWidth = 1;
    spectrumCtx.fillStyle = "#7e8992";
    spectrumCtx.font = "9px Cascadia Mono, Consolas, monospace";
    spectrumCtx.textBaseline = "middle";
    for (let i = 0; i <= 8; i += 1) {
      const y = g.top + g.height * i / 8;
      spectrumCtx.beginPath();
      spectrumCtx.moveTo(g.left, y);
      spectrumCtx.lineTo(g.right, y);
      spectrumCtx.stroke();
      const amplitude = state.reference - state.yRange * i / 8;
      spectrumCtx.textAlign = "right";
      spectrumCtx.fillText(amplitude.toFixed(0), g.left - 7, y);
    }
    for (let i = 0; i <= 10; i += 1) {
      const x = g.left + g.width * i / 10;
      spectrumCtx.beginPath();
      spectrumCtx.moveTo(x, g.top);
      spectrumCtx.lineTo(x, g.bottom);
      spectrumCtx.stroke();
      if (state.viewStart != null) {
        const frequency = state.viewStart + (state.viewStop - state.viewStart) * i / 10;
        spectrumCtx.textAlign = i === 0 ? "left" : i === 10 ? "right" : "center";
        spectrumCtx.textBaseline = "top";
        spectrumCtx.fillText(formatCompactFrequency(frequency), x, g.bottom + 7);
      }
    }
    spectrumCtx.fillStyle = "#65717a";
    spectrumCtx.textAlign = "left";
    spectrumCtx.textBaseline = "top";
    spectrumCtx.fillText(state.unit, 7, 7);
    spectrumCtx.restore();
  }

  // ---------------------------------------------------------------- carriers
  // The detector runs at full frame rate on the server; the DOM table is
  // repainted at 5 Hz so a 30 fps stream never competes with layout work.
  const CARRIER_TABLE_INTERVAL_MS = 200;

  function updateCarriers(header) {
    state.carriers = header.carriers || [];
    state.carrierUnit = header.unit;
    if (state.selectedCarrier != null
      && !state.carriers.some((carrier) => carrier.id === state.selectedCarrier)) {
      state.selectedCarrier = null;
    }
    const now = performance.now();
    if (now - state.lastCarrierPaint < CARRIER_TABLE_INTERVAL_MS) return;
    state.lastCarrierPaint = now;
    paintCarrierTable(header);
  }

  function paintCarrierTable(header) {
    const body = $("carrierTable");
    const carriers = state.carriers;
    $("carrierActive").textContent = String(carriers.length);
    const occupancy = carriers.reduce((total, c) => total + (c.occupied_bandwidth || 0), 0);
    $("carrierOccupancy").textContent = occupancy > 0 ? formatFrequency(occupancy, 3) : "—";
    if (!carriers.length) {
      body.innerHTML = '<tr class="placeholder-row"><td colspan="4">No carriers detected</td></tr>';
      return;
    }
    const unit = header.unit;
    const rows = carriers.map((carrier) => {
      const centre = (carrier.center_frequency / 1e6).toFixed(4);
      const obw = (carrier.occupied_bandwidth / 1e3).toFixed(1);
      const power = Number.isFinite(carrier.power) ? carrier.power.toFixed(2) : "—";
      const classes = [];
      if (carrier.id === state.selectedCarrier) classes.push("selected");
      if (carrier.confidence < 0.5) classes.push("stale");
      const title = Number.isFinite(carrier.snr) ? ` title="SNR ${carrier.snr.toFixed(1)} dB"` : "";
      return `<tr class="${classes.join(" ")}" data-carrier="${carrier.id}"${title}>`
        + `<td class="carrier-id">C${carrier.id}</td>`
        + `<td>${centre}</td><td>${obw}</td><td>${power === "—" ? power : `${power} ${unit}`}</td></tr>`;
    });
    body.innerHTML = rows.join("");
    body.querySelectorAll("tr[data-carrier]").forEach((row) => {
      row.addEventListener("click", () => selectCarrier(Number(row.dataset.carrier)));
    });
  }

  function selectCarrier(id) {
    const carrier = state.carriers.find((item) => item.id === id);
    if (!carrier || !state.latestFrame) return;
    state.selectedCarrier = state.selectedCarrier === id ? null : id;
    if (state.selectedCarrier != null) {
      // Frame the carrier with one occupied bandwidth of context either side.
      const margin = Math.max(carrier.occupied_bandwidth, state.latestFrame.header.rbw * 20);
      const { header } = state.latestFrame;
      const low = header.frequency_start;
      const high = header.frequency_start + header.frequency_step * (header.bins - 1);
      state.viewStart = Math.max(low, carrier.center_frequency - carrier.occupied_bandwidth / 2 - margin);
      state.viewStop = Math.min(high, carrier.center_frequency + carrier.occupied_bandwidth / 2 + margin);
      clearWaterfall();
    }
    paintCarrierTable(state.latestFrame.header);
  }

  function exportCarrierCsv() {
    if (!state.carriers.length) return toast("No carriers are currently detected", "error");
    const header = state.latestFrame.header;
    const calibrated = header.power_calibrated && Number.isFinite(header.power_offset_db);
    const unit = calibrated ? "dbm" : "dbfs";
    const columns = [
      "timestamp_utc", "carrier_id", "center_frequency_hz", "occupied_bandwidth_hz",
      `band_power_${unit}`, `peak_power_${unit}`, `noise_floor_${unit}`,
      "snr_db", "left_bin", "right_bin", "confidence", "age_frames",
    ];
    const stamp = new Date(header.timestamp * 1000).toISOString();
    const cell = (value) => (Number.isFinite(value) ? value : "");
    const lines = [columns.join(",")];
    for (const carrier of state.carriers) {
      lines.push([
        stamp, carrier.id, carrier.center_frequency, carrier.occupied_bandwidth,
        cell(carrier.power), cell(carrier.peak_power), cell(carrier.noise_floor),
        cell(carrier.snr), carrier.left, carrier.right, carrier.confidence, carrier.age,
      ].join(","));
    }
    downloadBlob(new Blob([lines.join("\n")], { type: "text/csv" }), `carriers-${Date.now()}.csv`);
  }

  function drawCarriers(g, header) {
    spectrumCtx.save();
    spectrumCtx.textBaseline = "top";
    for (const carrier of header.carriers || []) {
      const leftFreq = header.frequency_start + carrier.left * header.frequency_step;
      const rightFreq = header.frequency_start + carrier.right * header.frequency_step;
      const left = Math.max(g.left, frequencyToX(leftFreq, g));
      const right = Math.min(g.right, frequencyToX(rightFreq, g));
      if (right <= g.left || left >= g.right) continue;
      const selected = carrier.id === state.selectedCarrier;
      const alpha = selected ? .26 : .13;
      const gradient = spectrumCtx.createLinearGradient(left, 0, right, 0);
      gradient.addColorStop(0, "rgba(69, 213, 154, .02)");
      gradient.addColorStop(.5, `rgba(69, 213, 154, ${alpha})`);
      gradient.addColorStop(1, "rgba(69, 213, 154, .02)");
      spectrumCtx.fillStyle = gradient;
      spectrumCtx.fillRect(left, g.top, right - left, g.height);
      spectrumCtx.strokeStyle = selected ? "rgba(120, 255, 200, .8)" : "rgba(69, 213, 154, .35)";
      spectrumCtx.strokeRect(left, g.top, right - left, g.height);

      // Occupied-bandwidth extent marker at the measured centre frequency.
      const centreX = frequencyToX(carrier.center_frequency, g);
      if (centreX > g.left && centreX < g.right) {
        spectrumCtx.setLineDash([3, 3]);
        spectrumCtx.strokeStyle = "rgba(69, 213, 154, .5)";
        spectrumCtx.beginPath();
        spectrumCtx.moveTo(centreX, g.top);
        spectrumCtx.lineTo(centreX, g.bottom);
        spectrumCtx.stroke();
        spectrumCtx.setLineDash([]);
      }

      if (right - left > 26) {
        const power = Number.isFinite(carrier.power) ? `  ${carrier.power.toFixed(1)} ${header.unit}` : "";
        const label = `C${carrier.id}${power}`;
        spectrumCtx.font = "bold 9px Cascadia Mono, Consolas, monospace";
        const width = spectrumCtx.measureText(label).width + 8;
        const boxLeft = Math.min(left + 3, g.right - width);
        spectrumCtx.fillStyle = "rgba(3, 12, 8, .82)";
        spectrumCtx.fillRect(boxLeft, g.top + 3, width, 13);
        spectrumCtx.fillStyle = selected ? "#b6ffd9" : "#45d59a";
        spectrumCtx.fillText(label, boxLeft + 4, g.top + 5);
      }
    }
    spectrumCtx.restore();
  }

  function drawTrace(g, header, values, name, startIndex, stopIndex) {
    const count = Math.max(1, stopIndex - startIndex + 1);
    const step = Math.max(1, Math.floor(count / Math.max(g.width * 1.4, 1)));
    spectrumCtx.save();
    spectrumCtx.beginPath();
    spectrumCtx.rect(g.left, g.top, g.width, g.height);
    spectrumCtx.clip();
    spectrumCtx.beginPath();
    let started = false;
    for (let i = startIndex; i <= stopIndex; i += step) {
      const frequency = header.frequency_start + i * header.frequency_step;
      const x = frequencyToX(frequency, g);
      const y = amplitudeToY(values[i], g);
      if (!started) {
        spectrumCtx.moveTo(x, y);
        started = true;
      } else {
        spectrumCtx.lineTo(x, y);
      }
    }
    spectrumCtx.strokeStyle = TRACE_COLORS[name];
    spectrumCtx.lineWidth = name === "amplitude" ? 1.35 : 1.1;
    spectrumCtx.globalAlpha = name === "amplitude" ? .98 : .9;
    spectrumCtx.shadowColor = TRACE_COLORS[name];
    spectrumCtx.shadowBlur = name === "amplitude" ? 4 : 2;
    spectrumCtx.stroke();
    spectrumCtx.restore();
  }

  function visiblePeak(values, startIndex, stopIndex) {
    let index = startIndex;
    for (let i = startIndex + 1; i <= stopIndex; i += 1) {
      if (values[i] > values[index]) index = i;
    }
    return index;
  }

  function drawWatchLines(g, header) {
    if (!state.watchList.length) return;
    spectrumCtx.save();
    spectrumCtx.setLineDash([2, 4]);
    spectrumCtx.lineWidth = 1;
    spectrumCtx.font = "9px Cascadia Mono, Consolas, monospace";
    spectrumCtx.textBaseline = "bottom";
    state.watchList.forEach((item, index) => {
      const x = frequencyToX(item.frequency, g);
      if (x < g.left || x > g.right) return;
      spectrumCtx.strokeStyle = watchColor(index);
      spectrumCtx.globalAlpha = state.logging ? .85 : .45;
      spectrumCtx.beginPath();
      spectrumCtx.moveTo(Math.round(x) + .5, g.top);
      spectrumCtx.lineTo(Math.round(x) + .5, g.bottom);
      spectrumCtx.stroke();
      spectrumCtx.globalAlpha = 1;
      spectrumCtx.fillStyle = watchColor(index);
      spectrumCtx.fillText(`F${index + 1}`, x + 3, g.bottom - 3);
    });
    spectrumCtx.restore();
  }

  function drawAutoPeak(g, header, values, startIndex, stopIndex) {
    // Mirrors renderer.py _update_auto_peak_marker(): the automatic peak
    // indicator is bound to whichever trace the marker system is attached to,
    // so a max-hold peak is never reported against a clear-write trace.
    if (!values || !values.length || !state.autoPeakVisible) return;
    const index = visiblePeak(values, startIndex, stopIndex);
    if (!Number.isFinite(values[index])) return;
    const x = frequencyToX(header.frequency_start + index * header.frequency_step, g);
    const y = amplitudeToY(values[index], g);
    spectrumCtx.save();
    spectrumCtx.fillStyle = "#ff4b55";
    spectrumCtx.shadowColor = "#ff4b55";
    spectrumCtx.shadowBlur = 8;
    spectrumCtx.beginPath();
    spectrumCtx.moveTo(x, y + 2);
    spectrumCtx.lineTo(x - 5, y - 7);
    spectrumCtx.lineTo(x + 5, y - 7);
    spectrumCtx.closePath();
    spectrumCtx.fill();
    spectrumCtx.restore();
  }

  function markerValue(marker, header, traces, delta = false) {
    const frequency = delta ? marker.deltaFrequency : marker.frequency;
    const index = traceIndexAtFrequency(frequency, header);
    return {
      index,
      frequency: header.frequency_start + index * header.frequency_step,
      amplitude: traces[state.markerTrace][index],
    };
  }

  function drawMarkers(g, header, traces) {
    for (const [id, marker] of state.markers) {
      const value = markerValue(marker, header, traces);
      marker.frequency = value.frequency;
      drawMarkerGlyph(g, id, value, MARKER_COLORS[id], false);
      if (marker.deltaFrequency != null) {
        const delta = markerValue(marker, header, traces, true);
        marker.deltaFrequency = delta.frequency;
        drawMarkerGlyph(g, id, delta, MARKER_COLORS[id], true);
      }
    }
    updateMarkerTable();
  }

  function drawMarkerGlyph(g, id, value, color, delta) {
    const x = frequencyToX(value.frequency, g);
    const y = amplitudeToY(value.amplitude, g);
    if (x < g.left || x > g.right || y < g.top - 20 || y > g.bottom + 20) return;
    const label = delta ? `M${id}Δ` : `M${id}`;
    spectrumCtx.save();
    spectrumCtx.strokeStyle = color;
    spectrumCtx.fillStyle = color;
    spectrumCtx.lineWidth = 1.4;
    spectrumCtx.beginPath();
    if (delta) {
      spectrumCtx.moveTo(x, y - 6); spectrumCtx.lineTo(x + 6, y);
      spectrumCtx.lineTo(x, y + 6); spectrumCtx.lineTo(x - 6, y);
      spectrumCtx.closePath();
    } else {
      spectrumCtx.arc(x, y, 5, 0, Math.PI * 2);
    }
    spectrumCtx.stroke();
    spectrumCtx.fillStyle = "rgba(3, 5, 6, .88)";
    spectrumCtx.fillRect(x + 8, y - 25, 96, 29);
    spectrumCtx.fillStyle = color;
    spectrumCtx.font = "bold 9px Cascadia Mono, Consolas, monospace";
    spectrumCtx.fillText(`${label}  ${value.amplitude.toFixed(1)} ${state.unit}`, x + 12, y - 14);
    spectrumCtx.fillStyle = "#aeb8bf";
    spectrumCtx.font = "8px Cascadia Mono, Consolas, monospace";
    spectrumCtx.fillText(formatFrequency(value.frequency, 4), x + 12, y - 4);
    spectrumCtx.restore();
  }

  function colorForLevel(value) {
    const normalized = Math.max(0, Math.min(1, (value - (state.reference - state.yRange)) / state.yRange));
    const stops = [
      [0.00, [5, 7, 19]],
      [0.22, [33, 27, 89]],
      [0.45, [16, 91, 122]],
      [0.67, [30, 166, 112]],
      [0.84, [214, 191, 65]],
      [1.00, [255, 239, 165]],
    ];
    let high = 1;
    while (high < stops.length && normalized > stops[high][0]) high += 1;
    high = Math.min(high, stops.length - 1);
    const low = Math.max(0, high - 1);
    const span = stops[high][0] - stops[low][0] || 1;
    const mix = (normalized - stops[low][0]) / span;
    return stops[low][1].map((channel, index) => Math.round(channel + (stops[high][1][index] - channel) * mix));
  }

  function drawWaterfallRow(frame) {
    const resized = fitCanvas(waterfall, waterfallCtx);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssWidth = waterfall.clientWidth;
    const cssHeight = waterfall.clientHeight;
    if (resized) {
      waterfallCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      waterfallCtx.fillStyle = "#030513";
      waterfallCtx.fillRect(0, 0, cssWidth, cssHeight);
    }
    waterfallCtx.save();
    waterfallCtx.setTransform(1, 0, 0, 1, 0, 0);
    waterfallCtx.drawImage(
      waterfall,
      0,
      0,
      waterfall.width,
      waterfall.height - dpr,
      0,
      dpr,
      waterfall.width,
      waterfall.height - dpr,
    );
    const rowWidth = Math.max(1, Math.floor(cssWidth * dpr));
    const row = waterfallCtx.createImageData(rowWidth, Math.max(1, Math.floor(dpr)));
    const values = frame.traces.amplitude;
    for (let x = 0; x < rowWidth; x += 1) {
      const index = Math.min(values.length - 1, Math.floor(x / rowWidth * values.length));
      const [r, g, b] = colorForLevel(values[index]);
      for (let y = 0; y < row.height; y += 1) {
        const p = (y * rowWidth + x) * 4;
        row.data[p] = r; row.data[p + 1] = g; row.data[p + 2] = b; row.data[p + 3] = 255;
      }
    }
    waterfallCtx.putImageData(row, 0, 0);
    waterfallCtx.restore();
  }

  function clearWaterfall() {
    fitCanvas(waterfall, waterfallCtx);
    waterfallCtx.fillStyle = "#030513";
    waterfallCtx.fillRect(0, 0, waterfall.clientWidth, waterfall.clientHeight);
  }

  const AUTO_PEAK_BLINK_MS = 700;

  function renderLoop(now) {
    if (now - state.lastPeakBlink >= AUTO_PEAK_BLINK_MS) {
      state.lastPeakBlink = now;
      state.autoPeakVisible = !state.autoPeakVisible;
    }
    drawSpectrum();
    if (state.latestFrame && state.renderedSequence !== state.frameSequence) {
      drawWaterfallRow(state.latestFrame);
      state.renderedSequence = state.frameSequence;
    }
    if (now - state.lastFpsTick >= 1000) {
      state.fps = state.receivedThisSecond * 1000 / (now - state.lastFpsTick);
      state.receivedThisSecond = 0;
      state.lastFpsTick = now;
      $("fpsStatus").textContent = `FPS: ${state.fps.toFixed(1)}`;
      if (state.logging) updateLoggerReadout();
    }
    requestAnimationFrame(renderLoop);
  }

  function markerAtPointer(x, y) {
    if (!state.latestFrame) return null;
    const g = plotGeometry();
    const { header, traces } = state.latestFrame;
    for (const [id, marker] of state.markers) {
      for (const delta of [false, true]) {
        if (delta && marker.deltaFrequency == null) continue;
        const value = markerValue(marker, header, traces, delta);
        const mx = frequencyToX(value.frequency, g);
        const my = amplitudeToY(value.amplitude, g);
        if (Math.hypot(x - mx, y - my) < 14) return { id, delta };
      }
    }
    return null;
  }

  function handlePointerDown(event) {
    if (!state.latestFrame) return;
    spectrum.setPointerCapture(event.pointerId);
    const rect = spectrum.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = markerAtPointer(x, y);
    state.dragging = hit
      ? { type: "marker", ...hit, startX: x }
      : { type: "pan", startX: x, viewStart: state.viewStart, viewStop: state.viewStop, moved: false };
  }

  function handlePointerMove(event) {
    if (!state.latestFrame) return;
    const rect = spectrum.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const g = plotGeometry();
    if (state.dragging) {
      if (state.dragging.type === "marker") {
        const frequency = Math.max(state.viewStart, Math.min(state.viewStop, xToFrequency(x, g)));
        const marker = state.markers.get(state.dragging.id);
        if (state.dragging.delta) marker.deltaFrequency = frequency;
        else marker.frequency = frequency;
      } else {
        const fraction = (x - state.dragging.startX) / g.width;
        if (Math.abs(x - state.dragging.startX) > 3) state.dragging.moved = true;
        const shift = -fraction * (state.dragging.viewStop - state.dragging.viewStart);
        const fullStart = state.latestFrame.header.frequency_start;
        const fullStop = fullStart + state.latestFrame.header.frequency_step * (state.latestFrame.header.bins - 1);
        const width = state.dragging.viewStop - state.dragging.viewStart;
        let start = state.dragging.viewStart + shift;
        start = Math.max(fullStart, Math.min(fullStop - width, start));
        state.viewStart = start;
        state.viewStop = start + width;
      }
      return;
    }
    if (x < g.left || x > g.right || y < g.top || y > g.bottom) {
      $("plotTooltip").hidden = true;
      return;
    }
    const frequency = xToFrequency(x, g);
    const index = traceIndexAtFrequency(frequency, state.latestFrame.header);
    const amplitude = state.latestFrame.traces[state.markerTrace][index];
    const tooltip = $("plotTooltip");
    tooltip.hidden = false;
    tooltip.style.left = `${Math.min(x + 12, rect.width - 150)}px`;
    tooltip.style.top = `${Math.max(7, y - 36)}px`;
    tooltip.textContent = `${formatFrequency(frequency, 5)} · ${amplitude.toFixed(2)} ${state.unit}`;
  }

  function handlePointerUp(event) {
    if (!state.dragging || !state.latestFrame) return;
    const rect = spectrum.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const g = plotGeometry();
    if (state.dragging.type === "pan" && !state.dragging.moved && state.activeMarker) {
      const frequency = Math.max(state.viewStart, Math.min(state.viewStop, xToFrequency(x, g)));
      state.markers.set(state.activeMarker, { frequency, deltaFrequency: null });
      updateMarkerTable();
    }
    state.dragging = null;
  }

  function handleWheel(event) {
    if (!state.latestFrame) return;
    event.preventDefault();
    const rect = spectrum.getBoundingClientRect();
    const g = plotGeometry();
    const pointerFrequency = xToFrequency(event.clientX - rect.left, g);
    const fullStart = state.latestFrame.header.frequency_start;
    const fullStop = fullStart + state.latestFrame.header.frequency_step * (state.latestFrame.header.bins - 1);
    const fullWidth = fullStop - fullStart;
    const oldWidth = state.viewStop - state.viewStart;
    const scale = event.deltaY > 0 ? 1.25 : .8;
    const newWidth = Math.max(fullWidth / 200, Math.min(fullWidth, oldWidth * scale));
    const anchor = (pointerFrequency - state.viewStart) / oldWidth;
    let start = pointerFrequency - newWidth * anchor;
    start = Math.max(fullStart, Math.min(fullStop - newWidth, start));
    state.viewStart = start;
    state.viewStop = start + newWidth;
  }

  function updateMarkerTable() {
    const body = $("markerTable");
    if (!state.markers.size || !state.latestFrame) {
      body.innerHTML = '<tr class="placeholder-row"><td colspan="4">Select a marker, then click the spectrum</td></tr>';
      $("deltaReadout").hidden = true;
      return;
    }
    const { header, traces } = state.latestFrame;
    const rows = [];
    for (const [id, marker] of [...state.markers.entries()].sort((a, b) => a[0] - b[0])) {
      const value = markerValue(marker, header, traces);
      let deltaText = "—";
      if (marker.deltaFrequency != null) {
        const delta = markerValue(marker, header, traces, true);
        deltaText = formatFrequency(delta.frequency - value.frequency, 3);
        if (id === state.activeMarker) {
          $("deltaReadout").hidden = false;
          $("deltaReadout").textContent =
            `M${id} ↔ M${id}Δ\nΔf  ${formatFrequency(delta.frequency - value.frequency, 5)}\n`
            + `ΔA  ${(delta.amplitude - value.amplitude).toFixed(2)} dB\n`
            + `REF ${value.amplitude.toFixed(2)} ${state.unit}  ·  Δ ${delta.amplitude.toFixed(2)} ${state.unit}`;
        }
      }
      rows.push(`<tr><td style="color:${MARKER_COLORS[id]}">M${id}</td><td>${formatFrequency(value.frequency, 4)}</td><td>${value.amplitude.toFixed(2)} ${state.unit}</td><td>${deltaText}</td></tr>`);
    }
    body.innerHTML = rows.join("");
    const active = state.markers.get(state.activeMarker);
    if (!active || active.deltaFrequency == null) $("deltaReadout").hidden = true;
  }

  function placeMarkerAtPeak() {
    if (!state.activeMarker || !state.latestFrame) {
      toast("Select M1–M6 before peak search", "error");
      return;
    }
    const { header, traces } = state.latestFrame;
    const start = traceIndexAtFrequency(state.viewStart, header);
    const stop = traceIndexAtFrequency(state.viewStop, header);
    const index = visiblePeak(traces[state.markerTrace], start, stop);
    state.markers.set(state.activeMarker, {
      frequency: header.frequency_start + index * header.frequency_step,
      deltaFrequency: null,
    });
  }

  function toggleDelta() {
    if (!state.activeMarker || !state.markers.has(state.activeMarker) || !state.latestFrame) {
      toast("Place the active marker before enabling delta", "error");
      return;
    }
    const marker = state.markers.get(state.activeMarker);
    marker.deltaFrequency = marker.deltaFrequency == null
      ? Math.min(state.viewStop, marker.frequency + (state.viewStop - state.viewStart) * .05)
      : null;
    $("deltaButton").classList.toggle("active", marker.deltaFrequency != null);
  }

  // ------------------------------------------------------------ amplitude log
  // Logs the amplitude of user-specified frequencies over time. Sampling is
  // frame-driven: a sample is only taken when a frame arrives at or after the
  // next due time, so a stalled stream leaves a gap in the timestamps rather
  // than duplicating the last good value.
  const LOG_ROW_LIMIT = 200000;
  const WATCH_COLORS = [
    "#45d59a", "#54b9ff", "#f3b74f", "#c58cff",
    "#ff7d7d", "#5ee6e0", "#ffa45c", "#9cd94a",
  ];

  function watchColor(index) {
    return WATCH_COLORS[index % WATCH_COLORS.length];
  }

  function addWatchFrequency() {
    const value = Number($("watchInput").value);
    const scale = Number($("watchUnit").value);
    if (!Number.isFinite(value) || value <= 0) {
      return toast("Enter a frequency to track", "error");
    }
    const frequency = value * scale;
    if (state.watchList.some((item) => Math.abs(item.frequency - frequency) < 1)) {
      return toast("That frequency is already tracked", "error");
    }
    if (state.logging) {
      // Adding a column mid-session would leave earlier rows short.
      return toast("Stop logging before changing the tracked frequencies", "error");
    }
    state.watchList.push({ id: state.watchSequence++, frequency, level: null });
    $("watchInput").value = "";
    renderWatchList();
  }

  function removeWatchFrequency(id) {
    if (state.logging) return toast("Stop logging before changing the tracked frequencies", "error");
    state.watchList = state.watchList.filter((item) => item.id !== id);
    renderWatchList();
  }

  function renderWatchList() {
    const list = $("watchList");
    if (!state.watchList.length) {
      list.innerHTML = '<li class="watch-empty">Add one or more frequencies to log.</li>';
    } else {
      list.innerHTML = state.watchList.map((item, index) => {
        const level = Number.isFinite(item.level)
          ? `${item.level.toFixed(2)} ${state.logUnit}`
          : "—";
        const stale = Number.isFinite(item.level) ? "" : " stale";
        return `<li data-watch="${item.id}">`
          + `<i class="watch-swatch" style="background:${watchColor(index)}"></i>`
          + `<span class="watch-freq">${formatFrequency(item.frequency, 6)}</span>`
          + `<span class="watch-level${stale}">${level}</span>`
          + `<button class="watch-remove" type="button" aria-label="Remove">×</button></li>`;
      }).join("");
      list.querySelectorAll("li[data-watch]").forEach((node) => {
        node.querySelector(".watch-remove").addEventListener("click", () => {
          removeWatchFrequency(Number(node.dataset.watch));
        });
      });
    }
    $("logToggleButton").disabled = !state.watchList.length;
    updateLoggerReadout();
  }

  // Amplitude at one tracked frequency. A single bin is fragile: HackRF tuning
  // error of a few ppm is several bins wide at 4.9 kHz RBW, so the detector
  // takes the peak over a small aperture around the requested frequency.
  function sampleAt(header, values, frequency) {
    const target = Math.round((frequency - header.frequency_start) / header.frequency_step);
    if (target < 0 || target >= values.length) return null;
    const aperture = state.watchAperture;
    const low = Math.max(0, target - aperture);
    const high = Math.min(values.length - 1, target + aperture);
    let best = null;
    for (let i = low; i <= high; i += 1) {
      if (!Number.isFinite(values[i])) continue;
      if (best === null || values[i] > best) best = values[i];
    }
    return best;
  }

  function sampleAmplitudeLog(header, traces) {
    if (!state.watchList.length) return;
    const values = traces[state.watchTrace] || traces.average || traces.amplitude;
    if (!values || !values.length) return;
    state.logUnit = header.unit;

    const levels = state.watchList.map((item) => {
      const level = sampleAt(header, values, item.frequency);
      item.level = level;
      return level;
    });

    const now = performance.now();
    if (now - state.lastWatchPaint > 200) {
      state.lastWatchPaint = now;
      renderWatchList();
    }
    if (!state.logging) return;

    const wall = Date.now();
    if (wall < state.logNextDue) return;
    // Advance on the grid rather than from `wall`, so interval error does not
    // accumulate over a long session.
    state.logNextDue += state.logIntervalMs
      * Math.max(1, Math.ceil((wall - state.logNextDue) / state.logIntervalMs));

    state.logRows.push({ time: header.timestamp * 1000, levels });
    if (state.logRows.length >= LOG_ROW_LIMIT) {
      stopLogging();
      toast(`Logging stopped at the ${LOG_ROW_LIMIT.toLocaleString()} sample buffer limit`, "error");
    }
    updateLoggerReadout();
  }

  function updateLoggerReadout() {
    const count = state.logRows.length;
    $("logCount").textContent = count.toLocaleString();
    $("logExportButton").disabled = count === 0;
    $("logClearButton").disabled = count === 0 || state.logging;
    $("logStatus").hidden = !state.logging;
    $("logStatus").textContent = `REC ${count.toLocaleString()}`;
    if (state.logging) {
      const seconds = Math.max(0, (Date.now() - state.logStartedAt) / 1000);
      const minutes = Math.floor(seconds / 60);
      $("logElapsed").textContent = minutes
        ? `${minutes}m ${String(Math.floor(seconds % 60)).padStart(2, "0")}s`
        : `${seconds.toFixed(0)}s`;
    }
  }

  function startLogging() {
    if (!state.latestFrame) return toast("Start acquisition before logging", "error");
    if (!state.watchList.length) return toast("Add at least one frequency to track", "error");
    if (state.logRows.length && state.logColumns.length !== state.watchList.length) {
      state.logRows = [];
    }
    state.logIntervalMs = Number($("logIntervalSelect").value);
    state.watchTrace = $("watchTrace").value;
    state.watchAperture = Number($("watchDetector").value);
    state.logColumns = state.watchList.map((item) => item.frequency);
    state.logging = true;
    state.logStartedAt = Date.now();
    state.logNextDue = state.logStartedAt;
    for (const id of ["logIntervalSelect", "watchTrace", "watchDetector", "watchAddButton"]) {
      $(id).disabled = true;
    }
    $("logToggleButton").textContent = "Stop logging";
    $("logToggleButton").classList.add("recording");
    document.querySelector(".logger-card").classList.add("recording");
    updateLoggerReadout();
    toast(`Logging ${state.watchList.length} frequency(s) every ${state.logIntervalMs} ms`);
  }

  function stopLogging() {
    if (!state.logging) return;
    state.logging = false;
    for (const id of ["logIntervalSelect", "watchTrace", "watchDetector", "watchAddButton"]) {
      $(id).disabled = false;
    }
    $("logToggleButton").textContent = "Start logging";
    $("logToggleButton").classList.remove("recording");
    document.querySelector(".logger-card").classList.remove("recording");
    updateLoggerReadout();
  }

  function logTraceLabel(key) {
    return {
      average: "average", amplitude: "clear_write",
      max_hold: "max_hold", min_hold: "min_hold",
    }[key] || key;
  }

  function buildLogCsv() {
    // Timestamp plus one amplitude column per tracked frequency, nothing else.
    const unit = state.logUnit.toLowerCase();
    const columns = ["timestamp_utc"].concat(
      state.logColumns.map((frequency) => `${(frequency / 1e6).toFixed(6)}MHz_${unit}`),
    );
    const lines = [columns.join(",")];
    for (const row of state.logRows) {
      lines.push([new Date(row.time).toISOString()].concat(
        row.levels.map((level) => (Number.isFinite(level) ? level.toFixed(3) : "")),
      ).join(","));
    }
    return lines.join("\n");
  }

  function exportAmplitudeLog() {
    if (!state.logRows.length) return toast("The amplitude log is empty", "error");
    const started = new Date(state.logRows[0].time);
    const pad = (value) => String(value).padStart(2, "0");
    const stamp = `${started.getFullYear()}-${pad(started.getMonth() + 1)}-${pad(started.getDate())}`
      + `_${pad(started.getHours())}${pad(started.getMinutes())}${pad(started.getSeconds())}`;
    downloadBlob(
      new Blob([buildLogCsv()], { type: "text/csv" }),
      `amplitude-log_${stamp}_${logTraceLabel(state.watchTrace)}.csv`,
    );
  }

  // ------------------------------------------------------------- log plotting
  const logPlot = { series: [], times: [], unit: "dB", title: "", hidden: new Set(), hover: null };

  function openLogPlot() {
    $("logPlotModal").hidden = false;
    if (!logPlot.series.length && state.logRows.length) plotCurrentSession();
    else drawLogPlot();
  }

  function plotCurrentSession() {
    if (!state.logRows.length) return toast("The amplitude log is empty", "error");
    loadLogPlot(
      state.logRows.map((row) => row.time),
      state.logColumns.map((frequency, index) => ({
        label: formatFrequency(frequency, 6),
        values: state.logRows.map((row) => row.levels[index]),
      })),
      state.logUnit,
      "Session buffer",
    );
  }

  // Parses the CSV this logger writes, and any CSV whose first column is a
  // timestamp and whose remaining columns are numeric.
  function parseLogCsv(text, name) {
    const rows = text.trim().split(/\r?\n/).filter(Boolean);
    if (rows.length < 2) throw new Error("The file contains no data rows");
    const headers = rows[0].split(",").map((cell) => cell.trim());
    const times = [];
    const columns = headers.slice(1).map(() => []);
    for (let r = 1; r < rows.length; r += 1) {
      const cells = rows[r].split(",");
      const time = Date.parse(cells[0]);
      if (!Number.isFinite(time)) continue;
      times.push(time);
      for (let c = 0; c < columns.length; c += 1) {
        // Number("") is 0, which would plot a blank cell as a 0 dB spike
        // rather than the gap it actually represents.
        const cell = (cells[c + 1] || "").trim();
        const value = cell === "" ? NaN : Number(cell);
        columns[c].push(Number.isFinite(value) ? value : null);
      }
    }
    if (!times.length) throw new Error("No parsable timestamps in the first column");
    const unitMatch = /_(dbm|dbfs)$/i.exec(headers[1] || "");
    const series = headers.slice(1)
      .map((label, index) => ({ label: label.replace(/_(dbm|dbfs)$/i, ""), values: columns[index] }))
      .filter((item) => item.values.some((value) => value !== null));
    if (!series.length) throw new Error("No numeric amplitude columns found");
    return { times, series, unit: unitMatch ? unitMatch[1].replace("dbm", "dBm").replace("dbfs", "dBFS") : "dB", title: name };
  }

  function loadLogPlot(times, series, unit, title) {
    logPlot.times = times;
    logPlot.series = series;
    logPlot.unit = unit;
    logPlot.title = title;
    logPlot.hidden = new Set();
    $("logPlotTitle").textContent = title;
    const span = (times[times.length - 1] - times[0]) / 1000;
    $("logPlotMeta").textContent =
      `${times.length.toLocaleString()} samples · ${series.length} series · ${span.toFixed(1)} s`;
    renderLogLegend();
    drawLogPlot();
  }

  function renderLogLegend() {
    $("logPlotLegend").innerHTML = logPlot.series.map((item, index) =>
      `<button type="button" data-series="${index}" class="${logPlot.hidden.has(index) ? "off" : ""}">`
      + `<i style="background:${watchColor(index)}"></i>${item.label}</button>`).join("");
    $("logPlotLegend").querySelectorAll("button").forEach((node) => {
      node.addEventListener("click", () => {
        const index = Number(node.dataset.series);
        if (logPlot.hidden.has(index)) logPlot.hidden.delete(index);
        else logPlot.hidden.add(index);
        renderLogLegend();
        drawLogPlot();
      });
    });
  }

  function drawLogPlot() {
    const canvas = $("logPlotCanvas");
    const ctx = canvas.getContext("2d");
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const visible = logPlot.series.filter((_, index) => !logPlot.hidden.has(index));
    $("logPlotEmpty").hidden = visible.length > 0;
    if (!visible.length) return;

    const g = { left: 58, right: width - 14, top: 14, bottom: height - 26 };
    g.width = g.right - g.left;
    g.height = g.bottom - g.top;

    let min = Infinity;
    let max = -Infinity;
    for (const item of visible) {
      for (const value of item.values) {
        if (value === null || !Number.isFinite(value)) continue;
        if (value < min) min = value;
        if (value > max) max = value;
      }
    }
    if (!Number.isFinite(min)) return;
    const pad = Math.max(1, (max - min) * 0.12);
    min -= pad;
    max += pad;

    const t0 = logPlot.times[0];
    const t1 = logPlot.times[logPlot.times.length - 1] || t0 + 1;
    const xOf = (time) => g.left + ((time - t0) / Math.max(1, t1 - t0)) * g.width;
    const yOf = (value) => g.bottom - ((value - min) / (max - min)) * g.height;

    ctx.strokeStyle = "rgba(255,255,255,.06)";
    ctx.fillStyle = "#606b75";
    ctx.font = "9px Cascadia Mono, Consolas, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 5; i += 1) {
      const value = min + ((max - min) * i) / 5;
      const y = Math.round(yOf(value)) + .5;
      ctx.beginPath();
      ctx.moveTo(g.left, y);
      ctx.lineTo(g.right, y);
      ctx.stroke();
      ctx.fillText(`${value.toFixed(1)}`, g.left - 7, y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i <= 4; i += 1) {
      const time = t0 + ((t1 - t0) * i) / 4;
      const x = Math.round(xOf(time)) + .5;
      ctx.beginPath();
      ctx.moveTo(x, g.top);
      ctx.lineTo(x, g.bottom);
      ctx.stroke();
      const elapsed = (time - t0) / 1000;
      const label = elapsed >= 120
        ? `${Math.floor(elapsed / 60)}m${String(Math.round(elapsed % 60)).padStart(2, "0")}`
        : `${elapsed.toFixed(1)}s`;
      ctx.fillText(label, x, g.bottom + 6);
    }
    ctx.save();
    ctx.translate(13, (g.top + g.bottom) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText(`Amplitude (${logPlot.unit})`, 0, 0);
    ctx.restore();

    // Long sessions carry far more samples than pixels; step so that at most
    // two points are drawn per horizontal pixel.
    const step = Math.max(1, Math.floor(logPlot.times.length / (g.width * 2)));
    ctx.lineWidth = 1.4;
    ctx.lineJoin = "round";
    logPlot.series.forEach((item, index) => {
      if (logPlot.hidden.has(index)) return;
      ctx.strokeStyle = watchColor(index);
      ctx.beginPath();
      let open = false;
      for (let i = 0; i < logPlot.times.length; i += step) {
        const value = item.values[i];
        if (value === null || !Number.isFinite(value)) { open = false; continue; }
        const x = xOf(logPlot.times[i]);
        const y = yOf(value);
        if (open) ctx.lineTo(x, y);
        else { ctx.moveTo(x, y); open = true; }
      }
      ctx.stroke();
    });

    if (logPlot.hover !== null) {
      const x = Math.round(xOf(logPlot.times[logPlot.hover])) + .5;
      ctx.strokeStyle = "rgba(255,255,255,.28)";
      ctx.beginPath();
      ctx.moveTo(x, g.top);
      ctx.lineTo(x, g.bottom);
      ctx.stroke();
    }
    logPlot.geometry = { g, xOf, t0, t1 };
  }

  function onLogPlotHover(event) {
    if (!logPlot.times.length || !logPlot.geometry) return;
    const rect = $("logPlotCanvas").getBoundingClientRect();
    const x = event.clientX - rect.left;
    const { g, t0, t1 } = logPlot.geometry;
    const tooltip = $("logPlotTooltip");
    if (x < g.left || x > g.right) {
      tooltip.hidden = true;
      logPlot.hover = null;
      drawLogPlot();
      return;
    }
    const time = t0 + ((x - g.left) / g.width) * (t1 - t0);
    let index = 0;
    let bestDelta = Infinity;
    for (let i = 0; i < logPlot.times.length; i += 1) {
      const delta = Math.abs(logPlot.times[i] - time);
      if (delta < bestDelta) { bestDelta = delta; index = i; }
    }
    logPlot.hover = index;
    const rows = logPlot.series
      .map((item, seriesIndex) => ({ item, seriesIndex }))
      .filter(({ seriesIndex }) => !logPlot.hidden.has(seriesIndex))
      .map(({ item, seriesIndex }) => {
        const value = item.values[index];
        const text = Number.isFinite(value) ? `${value.toFixed(2)} ${logPlot.unit}` : "—";
        return `<div><i style="background:${watchColor(seriesIndex)}"></i>${item.label} · ${text}</div>`;
      }).join("");
    tooltip.innerHTML = `<strong>${new Date(logPlot.times[index]).toLocaleTimeString()}</strong>${rows}`;
    tooltip.hidden = false;
    tooltip.style.left = `${Math.min(x + 14, rect.width - 190)}px`;
    tooltip.style.top = "18px";
    drawLogPlot();
  }

  function downloadBlob(blob, filename) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function exportCsv() {
    if (!state.latestFrame) return toast("No spectrum frame is available", "error");
    const { header, traces } = state.latestFrame;
    const calibrated = header.power_calibrated && Number.isFinite(header.power_offset_db);
    const names = ["amplitude", "max_hold", "min_hold", "average"];
    const columns = ["frequency_hz", ...names.map((name) => `${name}_dbfs`)];
    if (calibrated) columns.push(...names.map((name) => `${name}_dbm`));
    const lines = [columns.join(",")];
    for (let i = 0; i < header.bins; i += 1) {
      const frequency = header.frequency_start + i * header.frequency_step;
      const display = names.map((name) => traces[name][i]);
      const raw = calibrated ? display.map((value) => value - header.power_offset_db) : display;
      const row = [frequency, ...raw];
      if (calibrated) row.push(...display);
      lines.push(row.join(","));
    }
    downloadBlob(new Blob([lines.join("\n")], { type: "text/csv" }), `spectrum-${Date.now()}.csv`);
  }

  function exportScreenshot() {
    if (!state.latestFrame) return toast("No spectrum frame is available", "error");
    const scale = window.devicePixelRatio || 1;
    const output = document.createElement("canvas");
    output.width = Math.max(spectrum.width, waterfall.width);
    output.height = spectrum.height + waterfall.height + Math.floor(28 * scale);
    const context = output.getContext("2d");
    context.fillStyle = "#050607";
    context.fillRect(0, 0, output.width, output.height);
    context.drawImage(spectrum, 0, 0);
    context.fillStyle = "#0b0e10";
    context.fillRect(0, spectrum.height, output.width, 28 * scale);
    context.fillStyle = "#a7b2ba";
    context.font = `${10 * scale}px Cascadia Mono, Consolas, monospace`;
    context.fillText("WATERFALL HISTORY", 12 * scale, spectrum.height + 18 * scale);
    context.drawImage(waterfall, 0, spectrum.height + 28 * scale);
    output.toBlob((blob) => downloadBlob(blob, `spectrum-${Date.now()}.png`), "image/png");
  }

  function wireControls() {
    $("deviceSelect").addEventListener("change", () => {
      applyProfile($("deviceSelect").value, true);
      scheduleReconfigure();
    });
    $("sampleRateSelect").addEventListener("change", () => {
      applyProfile($("deviceSelect").value, false);
      scheduleReconfigure();
    });
    for (const id of ["centerInput", "centerUnit", "spanInput"]) {
      $(id).addEventListener("change", scheduleReconfigure);
      $(id).addEventListener("input", updateFrequencySummary);
    }
    $("gainInput").addEventListener("input", () => {
      $("gainOutput").value = `${$("gainInput").value} dB`;
      scheduleReconfigure();
    });
    $("referenceInput").addEventListener("change", () => {
      state.reference = Number($("referenceInput").value);
      clearWaterfall();
    });
    $("runButton").addEventListener("click", toggleRun);
    $("controlButton").addEventListener("click", () => claimControl(true));
    $("carrierToggle").addEventListener("click", () => {
      state.carriersVisible = !state.carriersVisible;
      $("carrierToggle").classList.toggle("active", state.carriersVisible);
      $("carrierToggle").setAttribute("aria-pressed", String(state.carriersVisible));
    });
    $("resetZoomButton").addEventListener("click", resetView);
    $("screenshotButton").addEventListener("click", exportScreenshot);
    $("csvButton").addEventListener("click", exportCsv);
    $("carrierCsvButton").addEventListener("click", exportCarrierCsv);
    $("logToggleButton").addEventListener("click", () => {
      if (state.logging) stopLogging();
      else startLogging();
    });
    $("logExportButton").addEventListener("click", exportAmplitudeLog);
    $("logClearButton").addEventListener("click", () => {
      state.logRows = [];
      $("logElapsed").textContent = "\u2014";
      updateLoggerReadout();
    });
    $("watchAddButton").addEventListener("click", addWatchFrequency);
    $("watchInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); addWatchFrequency(); }
    });
    $("watchTrace").addEventListener("change", () => { state.watchTrace = $("watchTrace").value; });
    $("watchDetector").addEventListener("change", () => {
      state.watchAperture = Number($("watchDetector").value);
    });
    $("logPlotButton").addEventListener("click", openLogPlot);
    $("logPlotClose").addEventListener("click", () => { $("logPlotModal").hidden = true; });
    $("logPlotModal").addEventListener("click", (event) => {
      if (event.target === $("logPlotModal")) $("logPlotModal").hidden = true;
    });
    $("logPlotCurrent").addEventListener("click", plotCurrentSession);
    $("logFileInput").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      try {
        const parsed = parseLogCsv(await file.text(), file.name);
        loadLogPlot(parsed.times, parsed.series, parsed.unit, parsed.title);
      } catch (error) {
        toast(`Could not read that CSV: ${error.message}`, "error");
      }
      event.target.value = "";
    });
    $("logPlotCanvas").addEventListener("mousemove", onLogPlotHover);
    $("logPlotCanvas").addEventListener("mouseleave", () => {
      $("logPlotTooltip").hidden = true;
      logPlot.hover = null;
      drawLogPlot();
    });
    window.addEventListener("resize", () => {
      if (!$("logPlotModal").hidden) drawLogPlot();
    });
    renderWatchList();
    window.addEventListener("beforeunload", (event) => {
      // The buffer lives only in this tab; a reload would silently discard it.
      if (state.logging || state.logRows.length) event.preventDefault();
    });
    $("carrierZoomOutButton").addEventListener("click", () => {
      state.selectedCarrier = null;
      resetView();
      clearWaterfall();
      if (state.latestFrame) paintCarrierTable(state.latestFrame.header);
    });
    $("resetMinButton").addEventListener("click", async () => {
      try {
        await api("/api/traces/min-hold/reset", {
          method: "POST",
          body: JSON.stringify({ client_id: clientId, force: false }),
        });
        toast("Min hold reset");
      } catch (error) {
        toast(error.message, "error");
      }
    });
    document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${button.dataset.tab}`));
    }));
    document.querySelectorAll(".marker-choice").forEach((button) => button.addEventListener("click", () => {
      state.activeMarker = Number(button.dataset.marker);
      document.querySelectorAll(".marker-choice").forEach((item) => item.classList.toggle("active", item === button));
      const marker = state.markers.get(state.activeMarker);
      $("deltaButton").classList.toggle("active", Boolean(marker && marker.deltaFrequency != null));
      updateMarkerTable();
    }));
    $("markerTraceSelect").addEventListener("change", () => {
      state.markerTrace = $("markerTraceSelect").value;
      // The desktop forces the selected trace visible so the auto-peak and
      // markers are never attached to a hidden curve.
      const checkbox = {
        amplitude: "traceLive", max_hold: "traceMax",
        min_hold: "traceMin", average: "traceAverage",
      }[state.markerTrace];
      if (checkbox && !$(checkbox).checked) $(checkbox).checked = true;
      state.autoPeakVisible = true;
      state.lastPeakBlink = performance.now();
      updateMarkerTable();
    });
    $("peakMarkerButton").addEventListener("click", placeMarkerAtPeak);
    $("deltaButton").addEventListener("click", toggleDelta);
    $("clearMarkersButton").addEventListener("click", () => {
      state.markers.clear();
      $("deltaButton").classList.remove("active");
      updateMarkerTable();
    });
    document.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => $(button.dataset.open).classList.add("open")));
    document.querySelectorAll("[data-collapse]").forEach((button) => button.addEventListener("click", () => $(button.dataset.collapse).classList.remove("open")));
    $("tokenForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      state.token = $("tokenInput").value.trim();
      sessionStorage.setItem("rf-analyzer-token", state.token);
      try {
        state.profiles = await api("/api/profiles");
        hideTokenDialog();
        populateProfiles();
        connectWebSocket();
      } catch {
        showTokenDialog(true);
      }
    });
    spectrum.addEventListener("pointerdown", handlePointerDown);
    spectrum.addEventListener("pointermove", handlePointerMove);
    spectrum.addEventListener("pointerup", handlePointerUp);
    spectrum.addEventListener("pointercancel", () => { state.dragging = null; });
    spectrum.addEventListener("pointerleave", () => { if (!state.dragging) $("plotTooltip").hidden = true; });
    spectrum.addEventListener("wheel", handleWheel, { passive: false });
    window.addEventListener("keydown", (event) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement) return;
      const key = event.key.toLowerCase();
      if (event.code === "Space") { event.preventDefault(); toggleRun(); }
      else if (key === "c") $("traceLive").click();
      else if (event.ctrlKey && key === "h") { event.preventDefault(); $("traceMax").click(); }
      else if (event.ctrlKey && key === "l") { event.preventDefault(); $("traceMin").click(); }
      else if (event.ctrlKey && key === "g") { event.preventDefault(); $("traceAverage").click(); }
      else if (key === "r") resetView();
      else if (key === "s") exportScreenshot();
      else if (event.ctrlKey && key === "e") { event.preventDefault(); exportCsv(); }
      else if (event.key === "Escape" && state.running) stopAcquisition();
    });
  }

  async function initialize() {
    try {
      wireControls();
    } catch (error) {
      // Never let a wiring fault block acquisition or the stream.
      console.error("[analyzer] wireControls failed", error);
      toast(`Interface wiring error: ${error.message}`, "error");
    }
    auditElements();
    state.reference = Number($("referenceInput").value);
    try {
      state.profiles = await api("/api/profiles");
      populateProfiles();
      const snapshot = await api(`/api/state?client_id=${encodeURIComponent(clientId)}`);
      handleServerState(snapshot);
      connectWebSocket();
    } catch (error) {
      if (!state.token) showTokenDialog();
      else toast(error.message, "error");
    }
    setInterval(async () => {
      if (state.socket && state.socket.readyState === WebSocket.OPEN) {
        state.socket.send("heartbeat");
      }
      try {
        const snapshot = await api(`/api/state?client_id=${encodeURIComponent(clientId)}`);
        handleServerState(snapshot);
      } catch { /* reconnect and token UI handle this */ }
    }, 15000);
    requestAnimationFrame(renderLoop);
  }

  initialize();
})();
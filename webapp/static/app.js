(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
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
  const waterfallHistory = document.createElement("canvas");
  const waterfallHistoryCtx = waterfallHistory.getContext("2d", { alpha: false });
  const WATERFALL_HISTORY_ROWS = 420;

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
      if (response.status === 409) updateControlUI(payload);
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
    $("emptyState").hidden = true;
  }

  function resetView() {
    if (!state.latestFrame) return;
    const { header } = state.latestFrame;
    state.viewStart = header.frequency_start;
    state.viewStop = header.frequency_start + header.frequency_step * (header.bins - 1);
  }

  function updateMeasurements(header, traces) {
    const peakTrace = traces[state.markerTrace] || traces.amplitude;
    let peak = null;
    if (peakTrace.length) {
      let index = 0;
      for (let i = 1; i < peakTrace.length; i += 1) {
        if (peakTrace[i] > peakTrace[index]) index = i;
      }
      peak = {
        frequency: header.frequency_start + header.frequency_step * index,
        amplitude: peakTrace[index],
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
    drawAutoPeak(
      g,
      header,
      traces[state.markerTrace] || traces.amplitude,
      startIndex,
      stopIndex,
    );
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

  function drawCarriers(g, header) {
    spectrumCtx.save();
    for (const carrier of header.carriers || []) {
      const leftFreq = header.frequency_start + carrier.left * header.frequency_step;
      const rightFreq = header.frequency_start + carrier.right * header.frequency_step;
      const left = Math.max(g.left, frequencyToX(leftFreq, g));
      const right = Math.min(g.right, frequencyToX(rightFreq, g));
      if (right <= g.left || left >= g.right) continue;
      const gradient = spectrumCtx.createLinearGradient(left, 0, right, 0);
      gradient.addColorStop(0, "rgba(69, 213, 154, .02)");
      gradient.addColorStop(.5, "rgba(69, 213, 154, .13)");
      gradient.addColorStop(1, "rgba(69, 213, 154, .02)");
      spectrumCtx.fillStyle = gradient;
      spectrumCtx.fillRect(left, g.top, right - left, g.height);
      spectrumCtx.strokeStyle = "rgba(0, 255, 13, 0.38)";
      spectrumCtx.strokeRect(left, g.top, right - left, g.height);
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

  function drawAutoPeak(g, header, values, startIndex, stopIndex) {
    if (!values.length) return;
    const index = visiblePeak(values, startIndex, stopIndex);
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
    const binCount = frame.header.bins;
    if (
      waterfallHistory.width !== binCount
      || waterfallHistory.height !== WATERFALL_HISTORY_ROWS
    ) {
      waterfallHistory.width = binCount;
      waterfallHistory.height = WATERFALL_HISTORY_ROWS;
      waterfallHistoryCtx.fillStyle = "#030513";
      waterfallHistoryCtx.fillRect(
        0,
        0,
        waterfallHistory.width,
        waterfallHistory.height,
      );
    }
    waterfallHistoryCtx.drawImage(
      waterfallHistory,
      0,
      0,
      waterfallHistory.width,
      waterfallHistory.height - 1,
      0,
      1,
      waterfallHistory.width,
      waterfallHistory.height - 1,
    );
    const row = waterfallHistoryCtx.createImageData(binCount, 1);
    const values = frame.traces.amplitude;
    for (let index = 0; index < binCount; index += 1) {
      const [r, g, b] = colorForLevel(values[index]);
      const pixel = index * 4;
      row.data[pixel] = r;
      row.data[pixel + 1] = g;
      row.data[pixel + 2] = b;
      row.data[pixel + 3] = 255;
    }
    waterfallHistoryCtx.putImageData(row, 0, 0);
  }

  function drawWaterfallViewport() {
    fitCanvas(waterfall, waterfallCtx);
    waterfallCtx.save();
    waterfallCtx.setTransform(1, 0, 0, 1, 0, 0);
    waterfallCtx.fillStyle = "#030513";
    waterfallCtx.fillRect(0, 0, waterfall.width, waterfall.height);

    if (!state.latestFrame || waterfallHistory.width <= 1) {
      waterfallCtx.restore();
      return;
    }

    const { header } = state.latestFrame;
    const fullStart = header.frequency_start;
    const fullStop = fullStart + header.frequency_step * (header.bins - 1);
    const fullWidth = Math.max(header.frequency_step, fullStop - fullStart);
    const sourceStart = Math.max(
      0,
      Math.min(
        waterfallHistory.width - 1,
        (state.viewStart - fullStart) / fullWidth * waterfallHistory.width,
      ),
    );
    const sourceStop = Math.max(
      sourceStart + 1,
      Math.min(
        waterfallHistory.width,
        (state.viewStop - fullStart) / fullWidth * waterfallHistory.width,
      ),
    );
    const dpr = waterfall.width / Math.max(1, waterfall.clientWidth);
    const destinationLeft = 57 * dpr;
    const destinationWidth = Math.max(
      1,
      (waterfall.clientWidth - 68) * dpr,
    );
    waterfallCtx.imageSmoothingEnabled = true;
    waterfallCtx.drawImage(
      waterfallHistory,
      sourceStart,
      0,
      sourceStop - sourceStart,
      waterfallHistory.height,
      destinationLeft,
      0,
      destinationWidth,
      waterfall.height,
    );
    waterfallCtx.restore();
  }

  function clearWaterfall() {
    if (state.latestFrame) {
      waterfallHistory.width = state.latestFrame.header.bins;
      waterfallHistory.height = WATERFALL_HISTORY_ROWS;
      waterfallHistoryCtx.fillStyle = "#030513";
      waterfallHistoryCtx.fillRect(
        0,
        0,
        waterfallHistory.width,
        waterfallHistory.height,
      );
    }
    fitCanvas(waterfall, waterfallCtx);
    waterfallCtx.save();
    waterfallCtx.setTransform(1, 0, 0, 1, 0, 0);
    waterfallCtx.fillStyle = "#030513";
    waterfallCtx.fillRect(0, 0, waterfall.width, waterfall.height);
    waterfallCtx.restore();
  }

  function renderLoop(now) {
    drawSpectrum();
    if (state.latestFrame && state.renderedSequence !== state.frameSequence) {
      drawWaterfallRow(state.latestFrame);
      state.renderedSequence = state.frameSequence;
    }
    drawWaterfallViewport();
    if (now - state.lastFpsTick >= 1000) {
      state.fps = state.receivedThisSecond * 1000 / (now - state.lastFpsTick);
      state.receivedThisSecond = 0;
      state.lastFpsTick = now;
      $("fpsStatus").textContent = `FPS: ${state.fps.toFixed(1)}`;
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
      const traceControl = {
        amplitude: $("traceLive"),
        max_hold: $("traceMax"),
        min_hold: $("traceMin"),
        average: $("traceAverage"),
      }[state.markerTrace];
      traceControl.checked = true;
      if (state.latestFrame) {
        updateMeasurements(
          state.latestFrame.header,
          state.latestFrame.traces,
        );
      }
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
    wireControls();
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

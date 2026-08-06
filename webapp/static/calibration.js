/* Calibration panel for the web UI.
 *
 * Usage: place an empty container in index.html and call mountCalibrationPanel.
 *
 *   <div id="calibration-panel"></div>
 *   <script src="/static/calibration.js"></script>
 *   <script>mountCalibrationPanel(document.getElementById('calibration-panel'));</script>
 *
 * Self-contained: injects its own scoped styles, no framework, no build step,
 * no external fetches. Safe to vendor into the offline deployment bundle.
 */

(function () {
  "use strict";

  const CSS = `
  .cal-panel{font:13px/1.5 system-ui,Segoe UI,sans-serif;color:#d8d8d8}
  .cal-panel h3{margin:0 0 8px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#7fb2ff}
  .cal-card{background:#141821;border:1px solid #262c3a;border-radius:6px;padding:14px;margin-bottom:12px}
  .cal-status{font:12px/1.6 Consolas,ui-monospace,monospace;white-space:pre-wrap;color:#b9c2d0}
  .cal-hint{color:#7d8798;font-size:12px;margin:0 0 12px}
  .cal-actions{display:flex;gap:10px;flex-wrap:wrap}
  .cal-btn{flex:1 1 160px;min-height:38px;padding:0 14px;background:#1d2431;color:#e6e9ef;
    border:1px solid #33405a;border-radius:5px;cursor:pointer;font-size:13px}
  .cal-btn:hover:not(:disabled){background:#26314a;border-color:#4a5f8a}
  .cal-btn:disabled{opacity:.5;cursor:progress}
  .cal-btn.primary{background:#1e3a63;border-color:#33578f}
  .cal-report{font:12px/1.55 Consolas,ui-monospace,monospace;white-space:pre-wrap;
    background:#0d1016;border:1px solid #262c3a;border-radius:5px;padding:12px;
    min-height:150px;max-height:340px;overflow:auto;color:#c6cede}
  .cal-ok{color:#6ede8a}.cal-warn{color:#f0c04a}.cal-bad{color:#ff6b6b}
  .cal-flag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;margin-left:6px}
  .cal-flag.on{background:#17371f;color:#6ede8a}.cal-flag.off{background:#3a2118;color:#ff9a6b}
  `;

  function injectStyles() {
    if (document.getElementById("cal-panel-styles")) return;
    const style = document.createElement("style");
    style.id = "cal-panel-styles";
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  const HTML = `
  <div class="cal-card">
    <h3>Current Calibration</h3>
    <div class="cal-status" data-cal="status">Loading…</div>
  </div>
  <div class="cal-card">
    <h3>Calibration Workbook</h3>
    <p class="cal-hint">
      Download the workbook, fill the yellow cells against a known signal generator,
      then upload it. Offsets are solved and written automatically. Restart acquisition
      afterwards. Read the README sheet first — the attenuator pad and the 15&nbsp;minute
      warm-up matter more than the number of points.
    </p>
    <div class="cal-actions">
      <button class="cal-btn" data-cal="download">Download Template</button>
      <button class="cal-btn primary" data-cal="upload">Upload Filled Workbook</button>
    </div>
    <input type="file" accept=".xlsx" hidden data-cal="file">
  </div>
  <div class="cal-card">
    <h3>Solver Report</h3>
    <div class="cal-report" data-cal="report">Upload a workbook to see the solver output here.</div>
  </div>`;

  const flag = (on, yes, no) =>
    `<span class="cal-flag ${on ? "on" : "off"}">${on ? yes : no}</span>`;

  function renderStatus(el, s) {
    const f = s.frequency, p = s.power;
    const lines = [
      `Device      ${s.device_type}  serial ${s.serial || "(default)"}`,
      `Frequency   ${f.calibrated
        ? `fixed ${f.fixed_offset_hz >= 0 ? "+" : ""}${f.fixed_offset_hz.toFixed(0)} Hz, ` +
          `${f.ppm_offset >= 0 ? "+" : ""}${f.ppm_offset.toFixed(3)} ppm` +
          (f.residual_points ? `, +${f.residual_points}-point residual table` : "")
        : "not calibrated"}`,
    ];

    if (p.points) {
      lines.push(
        `Power       ${p.points} points, ` +
        `${(p.freq_min_hz / 1e6).toFixed(0)}–${(p.freq_max_hz / 1e6).toFixed(0)} MHz, ` +
        `ref gain ${p.reference_gain_db} dB`
      );
      lines.push(`Gain table  ${p.gain_points} gain point(s)`);
    } else if (p.legacy_offset_db !== null && p.legacy_offset_db !== undefined) {
      lines.push(`Power       single fixed offset ${p.legacy_offset_db.toFixed(2)} dB`);
    } else {
      lines.push("Power       not calibrated — amplitudes remain dBFS");
    }

    if (s.metadata && s.metadata.calibrated_at) {
      lines.push(`Last run    ${s.metadata.calibrated_at}  by ${s.metadata.operator || "unknown"}`);
    }

    el.innerHTML =
      lines.join("\n") +
      "\n\n" +
      flag(f.calibrated, "FREQ OK", "FREQ UNCAL") +
      flag(p.calibrated, "POWER OK", "POWER UNCAL");
  }

  function mountCalibrationPanel(root, options) {
    if (!root) throw new Error("mountCalibrationPanel: container element is required");
    const base = (options && options.baseUrl) || "/api/calibration";
    const onApplied = options && options.onApplied;

    injectStyles();
    root.classList.add("cal-panel");
    root.innerHTML = HTML;

    const pick = (name) => root.querySelector(`[data-cal="${name}"]`);
    const statusEl = pick("status");
    const reportEl = pick("report");
    const fileEl = pick("file");
    const btnDownload = pick("download");
    const btnUpload = pick("upload");

    async function refresh() {
      try {
        const response = await fetch(`${base}/status`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderStatus(statusEl, await response.json());
      } catch (err) {
        statusEl.innerHTML = `<span class="cal-bad">Could not read calibration status: ${err.message}</span>`;
      }
    }

    btnDownload.addEventListener("click", () => {
      // Plain navigation so the browser handles Content-Disposition itself;
      // a blob round-trip would needlessly buffer the workbook in memory.
      window.location.href = `${base}/template`;
      reportEl.textContent =
        "Template download started.\n\nFill the yellow cells on SETUP, FREQ_CAL and " +
        "POWER_CAL, then use 'Upload Filled Workbook'.";
    });

    btnUpload.addEventListener("click", () => fileEl.click());

    fileEl.addEventListener("change", async () => {
      const file = fileEl.files && fileEl.files[0];
      if (!file) return;

      btnUpload.disabled = btnDownload.disabled = true;
      btnUpload.textContent = "Solving…";
      reportEl.textContent = `Uploading ${file.name}…`;

      try {
        const body = new FormData();
        body.append("file", file);
        const response = await fetch(`${base}/upload`, { method: "POST", body });
        const data = await response.json().catch(() => ({}));

        const stamp = new Date().toLocaleString();
        const text = data.report || data.detail || `HTTP ${response.status}`;
        const cls = data.ok ? "cal-ok" : "cal-bad";
        const head = data.ok ? "CALIBRATION APPLIED" : "NOT APPLIED";
        reportEl.innerHTML =
          `<span class="${cls}">[${stamp}] ${head} — ${file.name}</span>\n\n` +
          text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

        if (data.ok) {
          await refresh();
          if (onApplied) onApplied(data);
        }
      } catch (err) {
        reportEl.innerHTML = `<span class="cal-bad">Upload failed: ${err.message}</span>`;
      } finally {
        fileEl.value = "";
        btnUpload.disabled = btnDownload.disabled = false;
        btnUpload.textContent = "Upload Filled Workbook";
      }
    });

    refresh();
    return { refresh };
  }

  window.mountCalibrationPanel = mountCalibrationPanel;
})();
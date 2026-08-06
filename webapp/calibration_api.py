"""FastAPI routes for the web calibration panel.

Mount into the existing web server with two lines:

    from web.calibration_api import router as calibration_router, set_device_resolver
    app.include_router(calibration_router)

Optionally teach it which device is connected so the template is pre-tagged and
the status endpoint reports the right serial:

    set_device_resolver(lambda: (streamer.device_type, streamer.serial))

Endpoints
---------
    GET  /api/calibration/status     current offsets, for the panel header
    GET  /api/calibration/template   .xlsx download
    POST /api/calibration/upload     multipart file -> solved -> written
"""

from __future__ import annotations

import io
from typing import Callable

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend.cal_workbook import apply_workbook, build_template, template_filename
from backend.calibration import PowerCalibration, load_device_calibration

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_resolver: Callable[[], tuple[str, str]] = lambda: ("HACKRF", "")
_on_applied: Callable[[], None] | None = None


def set_device_resolver(resolver: Callable[[], tuple[str, str]]) -> None:
    """Register a callable returning (device_type, serial)."""
    global _resolver
    _resolver = resolver


def set_applied_callback(callback: Callable[[], None]) -> None:
    """Register a callable invoked after a calibration is successfully written.

    Use it to reload the calibration into a running pipeline without a restart.
    """
    global _on_applied
    _on_applied = callback


def _identity(device: str | None, serial: str | None) -> tuple[str, str]:
    if device:
        return device.upper(), (serial or "")
    try:
        resolved_device, resolved_serial = _resolver()
        return (resolved_device or "HACKRF").upper(), (resolved_serial or "")
    except Exception:
        return "HACKRF", ""


@router.get("/status")
async def calibration_status(device: str | None = None, serial: str | None = None):
    device_type, device_serial = _identity(device, serial)
    cal = load_device_calibration(device_type, device_serial)
    power = PowerCalibration.from_calibration(cal)

    frequency_calibrated = bool(
        cal.get("frequency_axis_offset_hz")
        or cal.get("ppm_offset")
        or cal.get("frequency_offset_table")
    )
    span = power.frequency_range_hz

    return {
        "device_type": device_type,
        "serial": device_serial,
        "frequency": {
            "calibrated": frequency_calibrated,
            "fixed_offset_hz": float(cal.get("frequency_axis_offset_hz") or 0.0),
            "ppm_offset": float(cal.get("ppm_offset") or 0.0),
            "residual_points": len(cal.get("frequency_offset_table") or []),
        },
        "power": {
            "calibrated": power.valid,
            "points": len(power.base_table),
            "reference_gain_db": power.reference_gain_db,
            "gain_points": len(power.gain_table),
            "external_attenuation_db": power.external_attenuation_db,
            "freq_min_hz": span[0] if span else None,
            "freq_max_hz": span[1] if span else None,
            "legacy_offset_db": power.legacy_offset_db,
        },
        "metadata": power.metadata or {},
    }


@router.get("/template")
async def calibration_template(device: str | None = None, serial: str | None = None):
    device_type, device_serial = _identity(device, serial)
    payload = build_template(device_type, device_serial)
    filename = template_filename(device_type, device_serial)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload")
async def calibration_upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Upload the .xlsx workbook, not a CSV or an older .xls file.")

    payload = await file.read()
    if not payload:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Workbook is far larger than a calibration sheet should be.")

    result = apply_workbook(payload)
    body = {
        "ok": result.ok,
        "device_type": result.device_type,
        "serial": result.serial,
        "freq_points": result.freq_points,
        "power_points": result.power_points,
        "errors": result.errors,
        "warnings": result.warnings,
        "summary": result.summary,
        "rejected_rows": result.rejected_rows,
        "report": result.report(),
    }
    if not result.ok:
        return JSONResponse(body, status_code=422)

    if _on_applied:
        try:
            _on_applied()
        except Exception as exc:  # never fail the write because a reload hook threw
            body["warnings"].append(f"Calibration was saved but the live reload failed: {exc}")

    return body
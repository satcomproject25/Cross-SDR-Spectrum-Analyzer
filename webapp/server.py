"""FastAPI service that exposes the analyzer backend to browsers."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.websockets import WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.acquisition import create_acquisition
from backend.device_profiles import DEVICE_PROFILES
from backend.models import AcquisitionConfig
from webapp.protocol import pack_spectrum_frame


STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTROL_LEASE_SECONDS = 45.0


class AcquisitionRequest(BaseModel):
    client_id: str = Field(min_length=8, max_length=128)
    device_type: str
    center_frequency: float
    sample_rate: float
    span: float
    gain: float
    fft_size: int = 4096


class ClientRequest(BaseModel):
    client_id: str = Field(min_length=8, max_length=128)
    force: bool = False


@dataclass
class Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue


def validate_config(request: AcquisitionRequest) -> AcquisitionConfig:
    device_type = request.device_type.upper()
    profile = DEVICE_PROFILES.get(device_type)
    if profile is None:
        raise HTTPException(422, f"Unsupported SDR type: {request.device_type}")
    if not (
        profile["min_frequency_hz"]
        <= request.center_frequency
        <= profile["max_frequency_hz"]
    ):
        raise HTTPException(
            422, "Center frequency is outside the selected device range"
        )
    allowed_rates = {float(value) * 1e6 for value in profile["sample_rates"]}
    if request.sample_rate not in allowed_rates:
        raise HTTPException(
            422, "Sample rate is not in the selected device profile"
        )
    maximum_span = min(profile["max_span_hz"], request.sample_rate)
    if not (100e3 <= request.span <= maximum_span):
        raise HTTPException(422, "Span is outside the selected device profile")
    if not (0 <= request.gain <= profile["max_gain_db"]):
        raise HTTPException(422, "Gain is outside the selected device profile")
    if request.fft_size != 4096:
        raise HTTPException(422, "This release uses a fixed 4096-point FFT")
    return AcquisitionConfig(
        device_type=device_type,
        center_frequency=request.center_frequency,
        sample_rate=request.sample_rate,
        span=request.span,
        gain=request.gain,
        fft_size=request.fft_size,
    )


class AnalyzerCoordinator:
    """Own one SDR stream and publish latest-only frames to every browser."""

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._acquisition = None
        self._pending_config: AcquisitionConfig | None = None
        self._config: AcquisitionConfig | None = None
        self._status = "Idle"
        self._error = ""
        self._subscribers: dict[str, Subscriber] = {}
        self._controller_id: str | None = None
        self._controller_seen = 0.0
        self._frames_sent = 0

    def _controller_is_stale_locked(self) -> bool:
        return (
            self._controller_id is not None
            and time.monotonic() - self._controller_seen > CONTROL_LEASE_SECONDS
        )

    def claim_control(self, client_id: str, force: bool = False):
        with self._lock:
            if self._controller_is_stale_locked():
                self._controller_id = None
            if (
                self._controller_id is not None
                and self._controller_id != client_id
                and not force
            ):
                raise HTTPException(
                    409,
                    "Another browser currently controls the analyzer. "
                    "Use Take control to transfer it.",
                )
            self._controller_id = client_id
            self._controller_seen = time.monotonic()
        self._broadcast_state()

    def touch_control(self, client_id: str):
        with self._lock:
            if self._controller_id == client_id:
                self._controller_seen = time.monotonic()

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        subscriber_id = secrets.token_hex(12)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        with self._lock:
            self._subscribers[subscriber_id] = Subscriber(loop, queue)
        self._enqueue(queue, {"type": "state", **self.snapshot()})
        self._broadcast_state()
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: str):
        with self._lock:
            self._subscribers.pop(subscriber_id, None)
        self._broadcast_state()

    @staticmethod
    def _enqueue(queue: asyncio.Queue, message: bytes | dict[str, Any]):
        while queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(message)

    def _broadcast(self, message: bytes | dict[str, Any]):
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(
                self._enqueue, subscriber.queue, message
            )

    def _broadcast_state(self):
        self._broadcast({"type": "state", **self.snapshot()})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._controller_is_stale_locked():
                self._controller_id = None
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "status": self._status,
                "error": self._error,
                "config": asdict(self._config) if self._config else None,
                "controller_id": self._controller_id,
                "viewer_count": len(self._subscribers),
                "frames_sent": self._frames_sent,
            }

    def start(self, config: AcquisitionConfig, client_id: str):
        self.claim_control(client_id)
        with self._lock:
            self._error = ""
            if self._thread is not None and self._thread.is_alive():
                self._pending_config = config
                self._status = "Reconfiguring…"
                acquisition = self._acquisition
            else:
                acquisition = None
                self._launch_locked(config)
        if acquisition is not None:
            acquisition.stop()
        self._broadcast_state()

    def _launch_locked(self, config: AcquisitionConfig):
        acquisition = create_acquisition(config)
        self._config = config
        self._acquisition = acquisition
        self._status = "Connecting…"
        self._thread = threading.Thread(
            target=self._run,
            args=(acquisition,),
            name="web-sdr-acquisition",
            daemon=True,
        )
        self._thread.start()

    def _run(self, acquisition):
        try:
            acquisition.run(self._on_frame, self._on_status)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._status = f"Device error: {exc}"
            self._broadcast_state()
        finally:
            with self._lock:
                pending = self._pending_config
                self._pending_config = None
                self._thread = None
                self._acquisition = None
                if pending is None:
                    self._status = "Idle" if not self._error else self._status
                else:
                    self._launch_locked(pending)
            self._broadcast_state()

    def _on_frame(self, frame):
        packet = pack_spectrum_frame(frame)
        with self._lock:
            self._frames_sent += 1
        self._broadcast(packet)

    def _on_status(self, status: str):
        with self._lock:
            self._status = status
        self._broadcast_state()

    def stop(self, client_id: str):
        self.claim_control(client_id)
        with self._lock:
            self._pending_config = None
            acquisition = self._acquisition
            self._status = "Stopping…"
        if acquisition is not None:
            acquisition.stop()
        else:
            with self._lock:
                self._status = "Idle"
        self._broadcast_state()

    def reset_min_hold(self, client_id: str):
        self.claim_control(client_id)
        with self._lock:
            acquisition = self._acquisition
        if acquisition is not None and hasattr(acquisition, "reset_min_hold"):
            acquisition.reset_min_hold()

    def shutdown(self):
        with self._lock:
            acquisition = self._acquisition
            self._pending_config = None
        if acquisition is not None:
            acquisition.stop()


def create_app(
    coordinator: AnalyzerCoordinator | None = None,
    access_token: str | None = None,
) -> FastAPI:
    coordinator = coordinator or AnalyzerCoordinator()
    configured_token = (
        access_token
        if access_token is not None
        else os.environ.get("FREQANALYZER_WEB_TOKEN", "")
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        coordinator.shutdown()

    app = FastAPI(
        title="RF Spectrum Analyzer",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.coordinator = coordinator
    app.state.access_token = configured_token

    def authorize(authorization: str | None = Header(default=None)):
        if not configured_token:
            return
        supplied = ""
        if authorization and authorization.lower().startswith("bearer "):
            supplied = authorization[7:]
        if not hmac.compare_digest(supplied, configured_token):
            raise HTTPException(401, "A valid campus access token is required")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/profiles", dependencies=[Depends(authorize)])
    async def profiles():
        return DEVICE_PROFILES

    @app.get("/api/state", dependencies=[Depends(authorize)])
    async def state(client_id: str = ""):
        if client_id:
            coordinator.touch_control(client_id)
        return coordinator.snapshot()

    @app.post("/api/control/claim", dependencies=[Depends(authorize)])
    async def claim_control(request: ClientRequest):
        coordinator.claim_control(request.client_id, request.force)
        return coordinator.snapshot()

    @app.post("/api/acquisition/start", dependencies=[Depends(authorize)])
    async def start_acquisition(request: AcquisitionRequest):
        config = validate_config(request)
        coordinator.start(config, request.client_id)
        return coordinator.snapshot()

    @app.post("/api/acquisition/stop", dependencies=[Depends(authorize)])
    async def stop_acquisition(request: ClientRequest):
        coordinator.stop(request.client_id)
        return coordinator.snapshot()

    @app.post("/api/traces/min-hold/reset", dependencies=[Depends(authorize)])
    async def reset_min_hold(request: ClientRequest):
        coordinator.reset_min_hold(request.client_id)
        return {"ok": True}

    @app.websocket("/ws/spectrum")
    async def spectrum_socket(websocket: WebSocket):
        supplied = websocket.query_params.get("token", "")
        if configured_token and not hmac.compare_digest(supplied, configured_token):
            await websocket.close(code=4401, reason="Invalid access token")
            return
        client_id = websocket.query_params.get("client_id", "")
        if client_id:
            coordinator.touch_control(client_id)
        await websocket.accept()
        subscriber_id, queue = coordinator.subscribe()

        async def send_messages():
            while True:
                message = await queue.get()
                if isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    await websocket.send_json(message)

        async def receive_heartbeats():
            while True:
                await websocket.receive_text()
                if client_id:
                    coordinator.touch_control(client_id)

        sender = asyncio.create_task(send_messages())
        receiver = asyncio.create_task(receive_heartbeats())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            receiver.cancel()
            coordinator.unsubscribe(subscriber_id)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()


def main():
    parser = argparse.ArgumentParser(description="Run the browser spectrum analyzer")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="127.0.0.1 for local use; 0.0.0.0 for campus/LAN access",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--token",
        default=None,
        help="Optional access token required by API and WebSocket clients",
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        create_app(access_token=args.token),
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

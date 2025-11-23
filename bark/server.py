"""Lightweight FastAPI server exposing Bark synthesis routes.

This module exposes a FastAPI application with optional request authentication,
rate limiting, bounded job queues, and async-safe background processing for
audio/video generation. Generation hooks and instrumentation callbacks can be
injected for observability.
"""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

import anyio
import numpy as np
from fastapi import Depends, FastAPI, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, conint, confloat
from scipy.io.wavfile import write as write_wav

from .api import generate_audio, generate_multimedia
from .generation import SAMPLE_RATE
from .modalities import ControlEvent
from .video import VideoGenerationConfig


_MODELS_AVAILABLE = os.getenv("BARK_MODELS_AVAILABLE", "").lower() in {"1", "true", "yes"}


@dataclass
class ServiceConfig:
    """Runtime configuration and hooks for the Bark service."""

    audio_fn: Callable[..., np.ndarray]
    multimedia_fn: Callable[..., Any]
    models_ready: bool = _MODELS_AVAILABLE
    log_hook: Optional[Callable[[str, Dict[str, Any]], None]] = None
    metrics_hook: Optional[Callable[[str, Dict[str, Any]], None]] = None
    max_queue_size: int = int(os.getenv("BARK_MAX_QUEUE_SIZE", 8))
    concurrency_limit: int = int(os.getenv("BARK_MAX_CONCURRENCY", 2))
    rate_limit_per_minute: int = int(os.getenv("BARK_RATE_LIMIT_PER_MIN", 30))
    output_root: Path = Path(os.getenv("BARK_OUTPUT_ROOT", "outputs"))
    api_key: Optional[str] = os.getenv("BARK_API_KEY")


def _emit_hook(hook: Optional[Callable[[str, Dict[str, Any]], None]], event: str, payload: Dict[str, Any]) -> None:
    if hook:
        try:
            hook(event, payload)
        except Exception:  # pragma: no cover - hook robustness
            pass


def get_service_config() -> ServiceConfig:
    """Return the default service configuration.

    Using a function allows future dependency injection or overriding from
    tests/embedding applications.
    """

    return ServiceConfig(audio_fn=generate_audio, multimedia_fn=generate_multimedia)


class HealthResponse(BaseModel):
    status: str
    time: str
    version: str


class CapabilityResponse(BaseModel):
    modalities: List[str]
    video_presets: Dict[str, Tuple[int, int]]
    audio_bitrates: List[str]
    codecs: Dict[str, str]
    notes: List[str]


class VideoPayload(BaseModel):
    resolution: Tuple[conint(gt=0), conint(gt=0)] = (3840, 2160)
    fps: conint(gt=0) = 30
    enable_captions: bool = True
    realtime_layering: bool = True
    audio_bitrate: str = "320k"
    video_bitrate: str = "28M"
    codec: str = "libx264"
    audio_codec: str = "aac"

    def to_config(self) -> VideoGenerationConfig:
        return VideoGenerationConfig(
            resolution=self.resolution,
            fps=self.fps,
            video_bitrate=self.video_bitrate,
            audio_bitrate=self.audio_bitrate,
            enable_captions=self.enable_captions,
            realtime_layering=self.realtime_layering,
            codec=self.codec,
            audio_codec=self.audio_codec,
        )


_DEFAULT_DRY_RUN = not _MODELS_AVAILABLE


class SynthesisRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt to drive Bark.")
    caption_text: Optional[str] = Field(None, description="Override caption body.")
    modalities: List[str] = Field(default_factory=lambda: ["audio"], description="Requested outputs.")
    render_video: bool = Field(False, description="Whether to render a full MP4.")
    dry_run: bool = Field(
        _DEFAULT_DRY_RUN,
        description="Skip heavyweight generation and return plan only. Defaults to false only when models are available.",
    )
    output_path: Optional[Path] = Field(None, description="Directory or file prefix for artifacts.")
    text_temp: confloat(ge=0.0, le=1.5) = 0.7
    waveform_temp: confloat(ge=0.0, le=1.5) = 0.7
    control_events: Optional[List[ControlEvent]] = None
    routing_priorities: Optional[Dict[str, float]] = None
    video: Optional[VideoPayload] = None


class SynthesisResponse(BaseModel):
    job_id: str
    status: str
    plan: Dict[str, object]
    artifacts: Dict[str, str] = Field(default_factory=dict)


app = FastAPI(title="Bark Multimodal Service", version="0.1.0")


class ServiceError(Exception):
    """Raised when a predictable service-side issue occurs."""

    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthError(ServiceError):
    """Raised when authentication is required or invalid."""

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED)


class RateLimitError(ServiceError):
    """Raised when a caller exceeds rate limits."""

    def __init__(self, message: str = "Too Many Requests"):
        super().__init__(message, status.HTTP_429_TOO_MANY_REQUESTS)


class QueueFullError(ServiceError):
    """Raised when the job queue is saturated."""

    def __init__(self, message: str = "Job queue is full"):
        super().__init__(message, status.HTTP_429_TOO_MANY_REQUESTS)


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


_CAPABILITIES = CapabilityResponse(
    modalities=["audio", "video", "captions", "control_events"],
    video_presets={
        "4k": (3840, 2160),
        "qhd": (2560, 1440),
        "fhd": (1920, 1080),
    },
    audio_bitrates=["160k", "256k", "320k"],
    codecs={"video": "libx264", "audio": "aac"},
    notes=[
        "Set dry_run=false to trigger full synthesis when models are installed.",
        "render_video=true will automatically attach captions based on your prompt.",
    ],
)


_RATE_LIMIT_STATE: Dict[str, List[datetime]] = {}
_RATE_LIMIT_LOCK = asyncio.Lock()


@dataclass
class QueuedJob:
    job_id: str
    payload: SynthesisRequest
    plan: Dict[str, Any]
    future: asyncio.Future[Dict[str, str]]


_job_queue: asyncio.Queue[QueuedJob] = asyncio.Queue()
_job_status: Dict[str, Dict[str, Any]] = {}
_worker_tasks: List[asyncio.Task] = []


async def _auth_dependency(config: ServiceConfig = Depends(get_service_config), api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    if config.api_key and api_key != config.api_key:
        raise AuthError("Invalid or missing API key")


async def _rate_limit_dependency(request: Request, config: ServiceConfig = Depends(get_service_config)) -> None:
    client_id = request.client.host if request.client else "unknown"
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=1)
    async with _RATE_LIMIT_LOCK:
        history = _RATE_LIMIT_STATE.setdefault(client_id, [])
        _RATE_LIMIT_STATE[client_id] = [ts for ts in history if ts > window_start]
        if len(_RATE_LIMIT_STATE[client_id]) >= config.rate_limit_per_minute:
            raise RateLimitError()
        _RATE_LIMIT_STATE[client_id].append(now)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Simple heartbeat for frontends to verify connectivity."""

    return HealthResponse(status="ok", time=datetime.utcnow().isoformat() + "Z", version=app.version)


@app.get("/api/capabilities", response_model=CapabilityResponse)
async def capabilities() -> CapabilityResponse:
    """Return static capabilities describing enabled modalities and presets."""

    return _CAPABILITIES


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return cleaned or "artifact"


def _resolve_output_dir(path_hint: Optional[Path], job_id: str, config: ServiceConfig) -> Path:
    base_dir = config.output_root.resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    safe_job_id = _sanitize_filename(job_id)
    if path_hint is None:
        return base_dir / safe_job_id

    resolved_hint = (base_dir / path_hint).resolve() if not path_hint.is_absolute() else path_hint.resolve()
    if not str(resolved_hint).startswith(str(base_dir)):
        raise ServiceError("Output path must be inside the configured output root.", status.HTTP_400_BAD_REQUEST)

    if resolved_hint.suffix:
        return resolved_hint.with_name(_sanitize_filename(resolved_hint.stem)).with_suffix(resolved_hint.suffix)

    resolved_hint.mkdir(parents=True, exist_ok=True)
    return resolved_hint / safe_job_id


async def _write_wav_async(path: Path, audio: np.ndarray) -> None:
    buffer = BytesIO()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, write_wav, buffer, SAMPLE_RATE, np.nan_to_num(audio))
    buffer.seek(0)
    async with await anyio.open_file(path, "wb") as f:
        await f.write(buffer.read())


async def _process_job(job: "QueuedJob", config: ServiceConfig) -> Dict[str, str]:
    artifacts: Dict[str, str] = {}
    payload = job.payload
    loop = asyncio.get_running_loop()

    output_root = _resolve_output_dir(payload.output_path, job.job_id, config)

    try:
        audio = await loop.run_in_executor(
            None,
            config.audio_fn,
            payload.prompt,
            None,
            payload.text_temp,
            payload.waveform_temp,
            False,
            False,
            payload.control_events,
            payload.routing_priorities,
        )
        wav_path = output_root if output_root.suffix else output_root.with_suffix(".wav")
        await _write_wav_async(wav_path, audio)
        artifacts["audio"] = str(wav_path)

        if payload.render_video:
            cfg = payload.video.to_config() if payload.video else VideoGenerationConfig()
            mp4_path = output_root if output_root.suffix else output_root.with_suffix(".mp4")
            result = await loop.run_in_executor(
                None,
                config.multimedia_fn,
                payload.prompt,
                mp4_path,
                cfg,
                payload.caption_text,
                payload.text_temp,
                payload.waveform_temp,
                True,
            )
            artifacts.update(
                {
                    "video": str(result.video_path),
                    "captions": str(result.caption_path) if getattr(result, "caption_path", None) else "",
                    "muxed": str(result.muxed_path) if getattr(result, "muxed_path", None) else "",
                }
            )
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(f"Generation failed: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR)

    return artifacts


async def _worker(config: ServiceConfig, semaphore: asyncio.Semaphore) -> None:
    while True:
        job = await _job_queue.get()
        _job_status[job.job_id]["status"] = "running"
        _emit_hook(config.log_hook, "job_started", {"job_id": job.job_id})
        try:
            async with semaphore:
                artifacts = await _process_job(job, config)
            job.future.set_result(artifacts)
            _job_status[job.job_id].update({"status": "completed", "artifacts": artifacts})
            _emit_hook(config.metrics_hook, "job_completed", {"job_id": job.job_id})
        except Exception as exc:  # noqa: BLE001
            job.future.set_exception(exc)
            _job_status[job.job_id]["status"] = "failed"
            _job_status[job.job_id]["error"] = str(exc)
            _emit_hook(config.log_hook, "job_failed", {"job_id": job.job_id, "error": str(exc)})
        finally:
            _job_queue.task_done()


def _init_queue(config: ServiceConfig) -> None:
    global _job_queue, _worker_tasks
    _job_queue = asyncio.Queue(maxsize=config.max_queue_size)
    _worker_tasks = []
    _job_status.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_service_config()
    _init_queue(config)
    workers = max(1, config.concurrency_limit)
    semaphore = asyncio.Semaphore(workers)
    _worker_tasks.extend(asyncio.create_task(_worker(config, semaphore)) for _ in range(workers))
    try:
        yield
    finally:
        for task in _worker_tasks:
            task.cancel()
        await asyncio.gather(*_worker_tasks, return_exceptions=True)


app.router.lifespan_context = lifespan


@app.post("/api/bark/synthesize", response_model=SynthesisResponse, dependencies=[Depends(_auth_dependency), Depends(_rate_limit_dependency)])
async def synthesize(payload: SynthesisRequest, config: ServiceConfig = Depends(get_service_config)) -> SynthesisResponse:
    """Perform lightweight planning or full Bark synthesis based on caller flags."""

    if not payload.prompt.strip():
        raise ServiceError("Prompt cannot be empty.")

    job_id = f"job-{uuid4().hex[:8]}"
    plan = {
        "prompt_length": len(payload.prompt),
        "modalities": payload.modalities,
        "render_video": payload.render_video,
        "dry_run": payload.dry_run,
        "video_overrides": payload.video.dict() if payload.video else None,
        "routing_priorities": payload.routing_priorities or {},
    }

    if payload.dry_run:
        return SynthesisResponse(job_id=job_id, status="planned", plan=plan)

    if not config.models_ready:
        raise ServiceError("Models are not loaded; enable them to run full synthesis.", status.HTTP_503_SERVICE_UNAVAILABLE)

    if _job_queue.full():
        raise QueueFullError()

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Dict[str, str]] = loop.create_future()
    job = QueuedJob(job_id=job_id, payload=payload, plan=plan, future=future)
    _job_status[job_id] = {"status": "queued", "plan": plan}
    _emit_hook(config.log_hook, "job_queued", {"job_id": job_id})

    try:
        _job_queue.put_nowait(job)
    except asyncio.QueueFull:  # pragma: no cover - double safety
        raise QueueFullError()

    try:
        artifacts = await future
    except ServiceError as exc:
        raise exc
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(f"Generation failed: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR)

    return SynthesisResponse(job_id=job_id, status=_job_status[job_id]["status"], plan=plan, artifacts=artifacts)


def create_app() -> FastAPI:
    """Expose the ASGI app for embedding inside other servers."""

    return app


if __name__ == "__main__":  # pragma: no cover - convenience launcher
    import uvicorn

    uvicorn.run("bark.server:app", host="0.0.0.0", port=8000, reload=False)

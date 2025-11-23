"""Lightweight FastAPI server exposing Bark synthesis routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, conint, confloat
from scipy.io.wavfile import write as write_wav

from .api import generate_audio, generate_multimedia
from .generation import SAMPLE_RATE
from .modalities import ControlEvent
from .video import VideoGenerationConfig


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


class SynthesisRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt to drive Bark.")
    caption_text: Optional[str] = Field(None, description="Override caption body.")
    modalities: List[str] = Field(default_factory=lambda: ["audio"], description="Requested outputs.")
    render_video: bool = Field(False, description="Whether to render a full MP4.")
    dry_run: bool = Field(True, description="Skip heavyweight generation and return plan only.")
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


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Simple heartbeat for frontends to verify connectivity."""

    return HealthResponse(status="ok", time=datetime.utcnow().isoformat() + "Z", version=app.version)


@app.get("/api/capabilities", response_model=CapabilityResponse)
def capabilities() -> CapabilityResponse:
    """Return static capabilities describing enabled modalities and presets."""

    return _CAPABILITIES


def _resolve_output_dir(path_hint: Optional[Path], job_id: str) -> Path:
    if path_hint is None:
        out_dir = Path("outputs")
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / job_id
    if path_hint.suffix:
        # Full file path provided; drop extension for format-specific names below.
        return path_hint
    path_hint.mkdir(parents=True, exist_ok=True)
    return path_hint / job_id


@app.post("/api/bark/synthesize", response_model=SynthesisResponse)
def synthesize(payload: SynthesisRequest) -> SynthesisResponse:
    """Perform lightweight planning or full Bark synthesis based on caller flags."""

    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

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

    output_root = _resolve_output_dir(payload.output_path, job_id)
    artifacts: Dict[str, str] = {}

    try:
        audio = generate_audio(
            text=payload.prompt,
            history_prompt=None,
            text_temp=payload.text_temp,
            waveform_temp=payload.waveform_temp,
            silent=False,
            output_full=False,
            control_events=payload.control_events,
            routing_priorities=payload.routing_priorities,
        )
        wav_path = output_root if output_root.suffix else output_root.with_suffix(".wav")
        write_wav(str(wav_path), SAMPLE_RATE, np.nan_to_num(audio))
        artifacts["audio"] = str(wav_path)

        if payload.render_video:
            cfg = payload.video.to_config() if payload.video else VideoGenerationConfig()
            mp4_path = output_root if output_root.suffix else output_root.with_suffix(".mp4")
            result = generate_multimedia(
                text=payload.prompt,
                output_video=mp4_path,
                video_config=cfg,
                caption_text=payload.caption_text,
                text_temp=payload.text_temp,
                waveform_temp=payload.waveform_temp,
                silent=True,
            )
            artifacts.update(
                {
                    "video": str(result.video_path),
                    "captions": str(result.caption_path) if result.caption_path else "",
                    "muxed": str(result.muxed_path) if result.muxed_path else "",
                }
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

    return SynthesisResponse(job_id=job_id, status="completed", plan=plan, artifacts=artifacts)


def create_app() -> FastAPI:
    """Expose the ASGI app for embedding inside other servers."""

    return app


if __name__ == "__main__":  # pragma: no cover - convenience launcher
    import uvicorn

    uvicorn.run("bark.server:app", host="0.0.0.0", port=8000, reload=False)

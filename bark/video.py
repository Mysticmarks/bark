"""Utilities to render Bark audio into 4K/30FPS MP4s with captions."""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np
from moviepy.editor import AudioArrayClip, VideoClip

from .generation import SAMPLE_RATE


@dataclass
class VideoGenerationConfig:
    """Configuration for deterministic high-quality video rendering."""

    resolution: Tuple[int, int] = (3840, 2160)
    fps: int = 30
    video_bitrate: str = "28M"
    audio_bitrate: str = "320k"
    audio_sample_rate: int = SAMPLE_RATE
    enable_captions: bool = True
    caption_language: str = "en"
    realtime_layering: bool = True
    codec: str = "libx264"
    audio_codec: str = "aac"
    preset: str = "medium"


@dataclass
class CaptionSegment:
    """Represents a timed caption string."""

    start: float
    end: float
    text: str


@dataclass
class MultimediaResult:
    """Paths produced by :func:`render_multimodal_mp4`."""

    video_path: Path
    caption_path: Optional[Path]
    muxed_path: Optional[Path]


def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    millis = int(round((secs - int(secs)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{int(secs):02d}.{millis:03d}"


def write_webvtt(segments: Iterable[CaptionSegment], path: Path) -> Path:
    """Write a WebVTT caption file with default track disposition."""

    lines: List[str] = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _prompt_palette(prompt: str) -> np.ndarray:
    """Derive a deterministic RGB palette from a text prompt."""

    seed = abs(hash(prompt)) % (2**32)
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.35, 0.95, size=(3,)).astype(np.float32)
    accent = rng.uniform(0.05, 0.35, size=(3,)).astype(np.float32)
    return np.clip(base + accent, 0.0, 1.0)


def _build_layered_frame(
    t: float,
    duration: float,
    energy_profile: np.ndarray,
    palette: np.ndarray,
    resolution: Tuple[int, int],
    realtime: bool,
) -> np.ndarray:
    width, height = resolution
    x_axis = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y_axis = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    base_wave = 0.5 + 0.5 * np.sin(2 * np.pi * (x_axis[None, :] * 1.5 + y_axis * 0.5 + t))
    diffusion = base_wave[..., None] * palette[None, None, :]

    idx = min(len(energy_profile) - 1, int((t / duration) * len(energy_profile)))
    energy = energy_profile[idx]
    depth_mask = np.clip(energy * 2.0, 0.0, 1.0)
    layering = diffusion * (0.55 + 0.45 * depth_mask)

    if realtime:
        time_phase = (math.sin(t * 2 * math.pi) + 1.0) * 0.5
        layering *= 0.9 + 0.1 * time_phase

    frame = np.clip(layering * 255.0, 0, 255).astype(np.uint8)
    return frame


def render_multimodal_mp4(
    prompt: str,
    audio_array: np.ndarray,
    output_path: Path,
    caption_text: Optional[str] = None,
    config: Optional[VideoGenerationConfig] = None,
) -> MultimediaResult:
    """
    Render a 4K/30FPS MP4 by layering Bark audio, prompt-driven visuals, and captions.

    The video uses a lightweight generator so frames are produced in real time during
    encoding, keeping memory usage low while maintaining UHD fidelity.
    """

    cfg = config or VideoGenerationConfig()
    caption_text = caption_text or prompt
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clean_audio = np.nan_to_num(audio_array).astype(np.float32)
    if clean_audio.ndim == 1:
        clean_audio = clean_audio[:, None]

    duration = clean_audio.shape[0] / float(cfg.audio_sample_rate)
    samples_per_frame = max(1, int(clean_audio.shape[0] / max(1, int(duration * cfg.fps))))
    energy_profile = (
        np.abs(clean_audio[:, 0])
        .reshape(-1, samples_per_frame)
        .mean(axis=1)
        .astype(np.float32)
    )

    palette = _prompt_palette(prompt)

    def _make_frame(t: float) -> np.ndarray:
        return _build_layered_frame(
            t,
            duration=duration,
            energy_profile=energy_profile,
            palette=palette,
            resolution=cfg.resolution,
            realtime=cfg.realtime_layering,
        )

    video_clip = VideoClip(make_frame=_make_frame, duration=duration).set_fps(cfg.fps)
    audio_clip = AudioArrayClip(clean_audio, fps=cfg.audio_sample_rate)
    merged = video_clip.set_audio(audio_clip)

    merged.write_videofile(
        str(output_path),
        fps=cfg.fps,
        codec=cfg.codec,
        audio_codec=cfg.audio_codec,
        bitrate=cfg.video_bitrate,
        audio_bitrate=cfg.audio_bitrate,
        preset=cfg.preset,
        verbose=False,
        logger=None,
    )

    caption_path: Optional[Path] = None
    muxed_path: Optional[Path] = None
    if cfg.enable_captions:
        segments = [CaptionSegment(start=0.0, end=duration, text=caption_text)]
        caption_path = write_webvtt(segments, output_path.with_suffix(".vtt"))
        muxed_path = _mux_captions(output_path, caption_path)

    return MultimediaResult(video_path=output_path, caption_path=caption_path, muxed_path=muxed_path)


def _mux_captions(video_path: Path, caption_path: Path) -> Optional[Path]:
    """Attach captions as a default subtitle track when ffmpeg is available."""

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return None

    muxed_path = video_path.with_name(video_path.stem + "_captioned.mp4")
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(caption_path),
        "-c",
        "copy",
        "-c:s",
        "mov_text",
        "-disposition:s:0",
        "default",
        str(muxed_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return muxed_path

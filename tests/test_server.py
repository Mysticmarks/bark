import sys
import types
from pathlib import Path
from typing import Callable, List

import numpy as np
from fastapi.testclient import TestClient

moviepy_stub = types.ModuleType("moviepy")
editor_stub = types.ModuleType("moviepy.editor")
editor_stub.AudioArrayClip = object
editor_stub.VideoClip = object
moviepy_stub.editor = editor_stub
sys.modules.setdefault("moviepy", moviepy_stub)
sys.modules.setdefault("moviepy.editor", editor_stub)

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bark import server


class DummyMultimediaResult:
    def __init__(self, video_path: Path, caption_path: Path, muxed_path: Path):
        self.video_path = video_path
        self.caption_path = caption_path
        self.muxed_path = muxed_path


def _fake_audio(calls: List[str]) -> Callable[..., np.ndarray]:
    def _inner(prompt: str, *_: object, **__: object) -> np.ndarray:
        calls.append(prompt)
        return np.ones(160, dtype=np.float32)

    return _inner


def _fake_multimedia() -> Callable[..., DummyMultimediaResult]:
    def _inner(prompt: str, output_path: Path, *_: object, **__: object) -> DummyMultimediaResult:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video-bytes")
        caption = output_path.with_suffix(".srt")
        caption.write_text(f"caption for {prompt}")
        muxed = output_path.with_name(output_path.stem + "_muxed.mp4")
        muxed.write_bytes(b"muxed")
        return DummyMultimediaResult(video_path=output_path, caption_path=caption, muxed_path=muxed)

    return _inner


def create_test_client(tmp_path: Path, models_ready: bool = True):
    audio_calls: List[str] = []
    audio_fn = _fake_audio(audio_calls)
    multimedia_fn = _fake_multimedia()

    config = server.ServiceConfig(
        audio_fn=audio_fn,
        multimedia_fn=multimedia_fn,
        models_ready=models_ready,
        output_root=tmp_path,
        max_queue_size=4,
        concurrency_limit=2,
    )

    original_get_config = server.get_service_config
    server.get_service_config = lambda: config

    app = server.create_app()
    app.dependency_overrides[original_get_config] = lambda: config
    client = TestClient(app)
    client.__enter__()

    def _teardown() -> None:
        client.app.dependency_overrides.clear()
        client.__exit__(None, None, None)
        server.get_service_config = original_get_config

    return client, audio_calls, _teardown


def test_health_and_capabilities(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        health_resp = client.get("/api/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"

        cap_resp = client.get("/api/capabilities")
        assert cap_resp.status_code == 200
        body = cap_resp.json()
        assert "modalities" in body and "audio" in body["modalities"]
        assert body["video_presets"]["4k"] == [3840, 2160]
        assert calls == []
    finally:
        cleanup()


def test_dry_run_plan_without_generation(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        payload = {"prompt": "hello world"}
        resp = client.post("/api/bark/synthesize", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "planned"
        assert data["plan"]["dry_run"] is True
        assert data["plan"]["render_video"] is False
        assert calls == []
    finally:
        cleanup()


def test_full_generation_emits_audio_file(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        payload = {"prompt": "generate audio", "dry_run": False}
        resp = client.post("/api/bark/synthesize", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert calls == ["generate audio"]

        audio_path = Path(data["artifacts"]["audio"])
        assert audio_path.exists()
        assert audio_path.suffix == ".wav"
    finally:
        cleanup()


def test_full_generation_with_video_outputs(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        payload = {
            "prompt": "with video",
            "dry_run": False,
            "render_video": True,
            "video": {"resolution": [640, 360], "fps": 24},
        }
        resp = client.post("/api/bark/synthesize", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "completed"
        assert calls == ["with video"]

        artifacts = {key: Path(val) for key, val in data["artifacts"].items()}
        assert artifacts["video"].exists()
        assert artifacts["captions"].read_text().startswith("caption for")
        assert artifacts["muxed"].exists()
    finally:
        cleanup()


def test_output_path_sanitization_and_validation(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        malicious_payload = {"prompt": "escape", "dry_run": False, "output_path": "../../secret.wav"}
        bad_resp = client.post("/api/bark/synthesize", json=malicious_payload)
        assert bad_resp.status_code == 400

        payload = {"prompt": "custom path", "dry_run": False, "output_path": "custom.wav"}
        ok_resp = client.post("/api/bark/synthesize", json=payload)
        assert ok_resp.status_code == 200
        path = Path(ok_resp.json()["artifacts"]["audio"])
        assert path.exists()
        assert path.name == "custom.wav"
    finally:
        cleanup()


def test_rejects_empty_prompt(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        resp = client.post("/api/bark/synthesize", json={"prompt": "  ", "dry_run": False})
        assert resp.status_code == 400
        assert "Prompt cannot be empty" in resp.json()["error"]
        assert calls == []
    finally:
        cleanup()


def test_requires_loaded_models_for_full_generation(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path, models_ready=False)
    try:
        resp = client.post("/api/bark/synthesize", json={"prompt": "needs models", "dry_run": False})
        assert resp.status_code == 503
        assert "Models are not loaded" in resp.json()["error"]
        assert calls == []
    finally:
        cleanup()


def test_job_status_for_dry_run_and_missing_job(tmp_path):
    client, _, cleanup = create_test_client(tmp_path)
    try:
        resp = client.post("/api/bark/synthesize", json={"prompt": "dry"})
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        status_resp = client.get(f"/api/bark/jobs/{job_id}")
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["status"] == "planned"
        assert status_body["artifacts"] == {}
        assert status_body["plan"]["prompt_length"] == len("dry")

        missing_resp = client.get("/api/bark/jobs/unknown")
        assert missing_resp.status_code == 404
    finally:
        cleanup()


def test_job_status_updates_after_completion(tmp_path):
    client, calls, cleanup = create_test_client(tmp_path)
    try:
        resp = client.post("/api/bark/synthesize", json={"prompt": "status run", "dry_run": False})
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        status_resp = client.get(f"/api/bark/jobs/{job_id}")
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["status"] == "completed"
        assert Path(body["artifacts"]["audio"]).exists()
        assert calls == ["status run"]
    finally:
        cleanup()

import './style.css';
import { fetchAudioBlob, createSynthesisJob, getCapabilities, getHealth } from './api';
import { bootstrapScene, renderStats } from './scene';
import {
  log,
  renderAudio,
  renderCapabilities,
  renderFormErrors,
  renderJobs,
  renderResponseSummary,
  setConnectionStatus,
  toast
} from './ui';
import type { JobState, SynthesisResponse } from './types';

const dryRunToggle = document.getElementById('dryRun') as HTMLInputElement;
const renderVideoToggle = document.getElementById('renderVideoToggle') as HTMLInputElement;
const videoPreview = document.getElementById('videoPreview') as HTMLVideoElement;
const toggleTheme = document.getElementById('toggleTheme') as HTMLInputElement;
let rtcStream: MediaStream | null = null;

const jobs = new Map<string, JobState>();

function persistTheme() {
  const prefersLight = localStorage.getItem('bark-theme') === 'light';
  document.documentElement.classList.toggle('light', prefersLight);
  toggleTheme.checked = prefersLight;
}

function setTheme(light: boolean) {
  document.documentElement.classList.toggle('light', light);
  localStorage.setItem('bark-theme', light ? 'light' : 'dark');
}

function buildPayload() {
  const text = (document.getElementById('textPrompt') as HTMLTextAreaElement).value.trim();
  const resolution = (document.getElementById('videoResolution') as HTMLSelectElement).value
    .split('x')
    .map(Number);
  const fps = Number((document.getElementById('videoFps') as HTMLSelectElement).value);
  const captionText = (document.getElementById('captionText') as HTMLInputElement).value.trim() || text;
  const captionsEnabled = (document.getElementById('enableCaptions') as HTMLInputElement).checked;
  const realtime = (document.getElementById('enableRealtime') as HTMLInputElement).checked;
  const hdAudio = (document.getElementById('enableHdAudio') as HTMLInputElement).checked;
  const textTemp = Number((document.getElementById('textTemp') as HTMLInputElement).value) || 0.7;
  const waveformTemp = Number((document.getElementById('waveformTemp') as HTMLInputElement).value) || 0.7;
  const outputDir = (document.getElementById('outputDir') as HTMLInputElement).value.trim();
  const jobPrefix = (document.getElementById('jobPrefix') as HTMLInputElement).value.trim();
  const dryRun = dryRunToggle.checked;
  const renderVideo = renderVideoToggle.checked;

  const outputPath = jobPrefix ? `${outputDir || 'outputs'}/${jobPrefix}` : outputDir || undefined;

  return {
    text,
    resolution,
    fps,
    captionText,
    captionsEnabled,
    realtime,
    hdAudio,
    textTemp,
    waveformTemp,
    outputDir,
    jobPrefix,
    dryRun,
    renderVideo,
    outputPath
  };
}

function validate(payload: ReturnType<typeof buildPayload>) {
  const errors: string[] = [];
  if (!payload.text) errors.push('Prompt cannot be empty.');
  if (payload.textTemp < 0 || payload.textTemp > 1.5) errors.push('Text temperature must be 0-1.5.');
  if (payload.waveformTemp < 0 || payload.waveformTemp > 1.5)
    errors.push('Waveform temperature must be 0-1.5.');
  if (payload.fps <= 0) errors.push('FPS must be greater than zero.');
  return errors;
}

function toJobStatus(data: SynthesisResponse | null, fallbackId: string, prompt: string): JobState {
  const base = data || {
    job_id: fallbackId,
    status: 'queued',
    plan: {
      prompt_length: prompt.length,
      modalities: ['audio'],
      render_video: false,
      dry_run: true
    },
    artifacts: {}
  };
  return {
    id: base.job_id,
    status: base.status,
    plan: base.plan,
    artifacts: base.artifacts,
    progress: base.status === 'completed' ? 100 : 10,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    prompt
  };
}

function upsertJob(job: JobState) {
  jobs.set(job.id, job);
  renderJobs(Array.from(jobs.values()));
}

function updateJobProgress(id: string, progress: number, status?: JobState['status']) {
  const current = jobs.get(id);
  if (!current) return;
  current.progress = Math.min(progress, 100);
  current.updatedAt = Date.now();
  if (status) current.status = status;
  upsertJob(current);
}

async function handleAudioPlayback(artifacts: Record<string, string>, jobId: string) {
  const audioPath = artifacts.audio;
  if (!audioPath) return;
  try {
    const blob = await fetchAudioBlob(audioPath);
    const url = URL.createObjectURL(blob);
    renderAudio(url, `Job ${jobId}`);
    toast('Streaming audio artifact', 'success');
  } catch (error) {
    toast((error as Error).message || 'Audio playback failed', 'error');
  }
}

async function handlePrompt() {
  const payload = buildPayload();
  const errors = validate(payload);
  renderFormErrors(errors);
  if (errors.length) {
    toast('Please resolve validation errors', 'error');
    return;
  }

  const { text, captionText, resolution, fps, captionsEnabled, realtime, hdAudio, textTemp, waveformTemp, outputPath, dryRun, renderVideo } = payload;
  log('Queued text prompt for Bark synthesis.', '1D');
  log(
    `Targeting ${resolution[0]}×${resolution[1]} @ ${fps}FPS with ${hdAudio ? 'HD' : 'standard'} audio and captions ${
      captionsEnabled ? 'ON' : 'OFF'
    }.`,
    'video'
  );

  const requestBody = {
    prompt: text,
    caption_text: captionText,
    modalities: renderVideo ? ['audio', 'video'] : ['audio'],
    render_video: renderVideo,
    dry_run: dryRun,
    output_path: outputPath,
    text_temp: textTemp,
    waveform_temp: waveformTemp,
    video: {
      resolution,
      fps,
      enable_captions: captionsEnabled,
      realtime_layering: realtime,
      audio_bitrate: hdAudio ? '320k' : '160k',
      video_bitrate: renderVideo ? '28M' : '10M',
      codec: 'libx264',
      audio_codec: 'aac'
    }
  };

  const tempId = `job-${Date.now()}`;
  upsertJob(toJobStatus(null, tempId, text));
  toast('Synthesis started', 'success');

  try {
    const result = await createSynthesisJob(requestBody, {
      onEvent(data) {
        if (!data || typeof data !== 'object') return;
        const event = data as Partial<SynthesisResponse> & { progress?: number };
        if (event.job_id && jobs.has(event.job_id)) {
          updateJobProgress(event.job_id, event.progress ?? 50, event.status);
        }
      }
    });

    const job = toJobStatus(result, tempId, text);
    job.progress = result?.status === 'completed' ? 100 : job.progress;
    upsertJob(job);
    renderResponseSummary(result);
    if (job.status === 'planned') {
      toast('Dry-run plan complete', 'info');
    }
    if (job.artifacts?.audio) {
      await handleAudioPlayback(job.artifacts, job.id);
    }
  } catch (err) {
    updateJobProgress(tempId, 100, 'failed');
    toast((err as Error).message || 'Request failed', 'error');
    renderResponseSummary(null);
  }
}

function handleFilePreview() {
  const file = (document.getElementById('audioUpload') as HTMLInputElement).files?.[0];
  if (!file) {
    log('Upload an audio file to preview.', 'warn');
    return;
  }
  const url = URL.createObjectURL(file);
  const audio = new Audio(url);
  audio.play();
  log(`Previewing ${file.name} (local only).`, '1D/2D');
}

function buildVolumeTexture(files: File[]) {
  log(`Queued ${files.length} layer(s) for volume reconstruction.`, '3D');
}

function handleImages() {
  const files = Array.from((document.getElementById('imageUpload') as HTMLInputElement).files || []);
  const asVolume = (document.getElementById('enableVolume') as HTMLInputElement).checked;
  if (!files.length) {
    log('Add image layers or stacks first.', 'warn');
    return;
  }
  if (asVolume) {
    buildVolumeTexture(files);
  } else {
    log(`Loaded ${files.length} 2D frame(s) for conditioning.`, '2D');
  }
}

async function connectRtc() {
  if (rtcStream) {
    rtcStream.getTracks().forEach((t) => t.stop());
  }
  try {
    rtcStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    videoPreview.srcObject = rtcStream;
    setConnectionStatus('RTC Live', 'ok');
    log('WebRTC capture started — frames can feed Bark temporal stacks.', '4D');
  } catch (err) {
    log(`WebRTC unavailable: ${(err as Error).message}`, 'offline');
    setConnectionStatus('Offline', 'error');
  }
}

function captureFrame() {
  if (!rtcStream) {
    log('Connect WebRTC before capturing frames.', 'warn');
    return;
  }
  const track = rtcStream.getVideoTracks()[0];
  const imageCapture = new ImageCapture(track);
  imageCapture
    .grabFrame()
    .then(() => log('Captured frame for 4D stack (client-side stub).', '4D'))
    .catch((err) => log(`Capture failed: ${(err as Error).message}`, 'offline'));
}

function saveSession() {
  const entries = Array.from(document.querySelectorAll('.log-entry')).map((el) => el.textContent?.trim() ?? '');
  const blob = new Blob([entries.join('\n')], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'bark-session.log';
  a.click();
  URL.revokeObjectURL(url);
  log('Session saved locally.', 'session');
}

function clearLog() {
  const logEl = document.getElementById('log');
  if (logEl) logEl.innerHTML = '';
}

async function refreshHealth() {
  try {
    const res = await getHealth();
    setConnectionStatus(`Online · v${res.version}`, 'ok');
    log(`Backend heartbeat received at ${res.time}.`, 'network');
  } catch (err) {
    setConnectionStatus('Offline', 'error');
    log('Backend offline — requests will fall back to local stubs.', 'offline');
  }
}

async function loadCapabilities() {
  try {
    const data = await getCapabilities();
    renderCapabilities(data);
    log('Fetched backend capabilities.', 'network');
  } catch (err) {
    renderCapabilities(null);
  }
}

function bindControls() {
  document.getElementById('sendPrompt')?.addEventListener('click', handlePrompt);
  document.getElementById('previewAudio')?.addEventListener('click', handleFilePreview);
  document.getElementById('loadImages')?.addEventListener('click', handleImages);
  document.getElementById('connectRtc')?.addEventListener('click', connectRtc);
  document.getElementById('captureFrame')?.addEventListener('click', captureFrame);
  document.getElementById('saveSession')?.addEventListener('click', saveSession);
  document.getElementById('clearLog')?.addEventListener('click', clearLog);
  toggleTheme?.addEventListener('change', (event) => setTheme((event.target as HTMLInputElement).checked));
}

function init() {
  persistTheme();
  bindControls();
  renderStats();
  refreshHealth();
  loadCapabilities();
  bootstrapScene();
  toast('Ready to synthesize', 'info', 2000);
}

init();

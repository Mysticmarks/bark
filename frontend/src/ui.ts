import type { CapabilityResponse, JobState, SynthesisResponse, ToastKind } from './types';

const logEl = document.getElementById('log');
const statusEl = document.getElementById('connectionStatus');
const capabilityEl = document.getElementById('capabilityList');
const responseBodyEl = document.getElementById('responseBody');
const toastRoot = document.getElementById('toastRoot');
const audioPlayer = document.getElementById('audioPlayer') as HTMLAudioElement | null;
const audioMeta = document.getElementById('audioMeta');

export function setConnectionStatus(message: string, tone: 'ok' | 'error' | 'info' = 'ok') {
  if (!statusEl) return;
  const color = tone === 'ok' ? 'var(--accent)' : tone === 'error' ? '#f28b82' : 'var(--text)';
  statusEl.textContent = message;
  statusEl.setAttribute('data-tone', tone);
  (statusEl as HTMLElement).style.color = color;
}

export function log(message: string, tag = 'info') {
  if (!logEl) return;
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span>${message}</span><span class="pill">${tag}</span>`;
  logEl.prepend(entry);
}

export function renderCapabilities(data: CapabilityResponse | null) {
  if (!capabilityEl) return;
  if (!data) {
    capabilityEl.innerHTML = '<div>Capabilities unavailable.</div>';
    return;
  }

  const videoPresets = Object.entries(data.video_presets || {})
    .map(([label, res]) => `<div>${label.toUpperCase()}: ${res[0]}×${res[1]}</div>`)
    .join('');
  const audioRates = (data.audio_bitrates || []).join(', ');
  const notes = (data.notes || []).map((n) => `<div>• ${n}</div>`).join('');

  capabilityEl.innerHTML = `
    <h3>Live API Capabilities</h3>
    <div class="capability-grid">
      <div><strong>Modalities</strong><br/>${(data.modalities || []).join(', ')}</div>
      <div><strong>Video presets</strong><br/>${videoPresets}</div>
      <div><strong>Audio</strong><br/>${audioRates}</div>
      <div><strong>Codecs</strong><br/>Video: ${data.codecs?.video || 'n/a'}<br/>Audio: ${
    data.codecs?.audio || 'n/a'
  }</div>
    </div>
    <div class="hint" aria-live="polite">${notes}</div>
  `;
}

export function renderResponseSummary(result: SynthesisResponse | null) {
  if (!responseBodyEl) return;
  if (!result) {
    responseBodyEl.textContent = 'Waiting for synthesis...';
    return;
  }

  const artifacts = Object.entries(result.artifacts || {})
    .filter(([, value]) => Boolean(value))
    .map(([key, value]) => `${key}: ${value}`)
    .join('\n');

  const lines = [
    `Job: ${result.job_id || 'n/a'}`,
    `Status: ${result.status || 'unknown'}`,
    `Modalities: ${(result.plan?.modalities || []).join(', ') || 'none'}`,
    `Render video: ${result.plan?.render_video ? 'yes' : 'no'}`,
  ];

  if (artifacts) {
    lines.push('Artifacts:', artifacts);
  }

  responseBodyEl.textContent = lines.join('\n');
}

export function renderJobs(jobs: JobState[]) {
  const jobList = document.getElementById('jobList');
  if (!jobList) return;
  jobList.innerHTML = jobs
    .sort((a, b) => b.createdAt - a.createdAt)
    .map((job) => {
      return `
      <article class="job-card" aria-label="Job ${job.id}">
        <header class="job-meta">
          <div>${job.id}</div>
          <div>${new Date(job.createdAt).toLocaleTimeString()}</div>
        </header>
        <div>${job.prompt || 'Prompt withheld'}</div>
        <div class="job-meta">
          <span>Status: ${job.status}</span>
          <span>${job.plan.render_video ? 'Audio + Video' : 'Audio'}</span>
        </div>
        <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${job.progress}">
          <div class="progress__bar" style="width:${job.progress}%"></div>
        </div>
      </article>`;
    })
    .join('');
}

export function renderAudio(url: string, meta?: string) {
  if (!audioPlayer || !audioMeta) return;
  audioPlayer.src = url;
  audioMeta.textContent = meta || 'Streaming audio...';
  audioPlayer.play().catch(() => undefined);
}

export function toast(message: string, kind: ToastKind = 'info', ttl = 4000) {
  if (!toastRoot) return;
  const el = document.createElement('div');
  el.className = `toast ${kind === 'error' ? 'toast--error' : ''}`;
  el.textContent = message;
  toastRoot.append(el);
  window.setTimeout(() => el.remove(), ttl);
}

export function renderFormErrors(errors: string[]) {
  const container = document.getElementById('formErrors');
  if (!container) return;
  container.className = 'form-errors';
  container.innerHTML = errors.map((e) => `<div>${e}</div>`).join('');
}

import type {
  CapabilityResponse,
  HealthResponse,
  JobState,
  SynthesisResponse
} from './types';

const JSON_HEADERS = { 'Content-Type': 'application/json' } as const;

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error((payload as { detail?: string }).detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>('/api/health');
}

export async function getCapabilities(): Promise<CapabilityResponse> {
  return fetchJson<CapabilityResponse>('/api/capabilities');
}

function parseSseChunk(buffer: string, onEvent?: (data: unknown) => void) {
  const messages = buffer.split('\n\n');
  const remainder = messages.pop() ?? '';
  for (const message of messages) {
    const line = message
      .split('\n')
      .map((l) => l.trim())
      .find((l) => l.startsWith('data:'));
    if (!line) continue;
    const payload = line.replace('data:', '').trim();
    try {
      onEvent?.(JSON.parse(payload));
    } catch {
      onEvent?.(payload);
    }
  }
  return remainder;
}

export async function createSynthesisJob(
  payload: Record<string, unknown>,
  opts: { signal?: AbortSignal; onEvent?: (data: unknown) => void } = {}
): Promise<SynthesisResponse | null> {
  const response = await fetch('/api/bark/synthesize', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    signal: opts.signal
  });

  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('text/event-stream') && response.body) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = parseSseChunk(buffer, opts.onEvent);
    }
    return null;
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((data as { detail?: string }).detail || 'Request failed');
  }
  return data as SynthesisResponse;
}

export async function pollJob(jobId: string): Promise<JobState | null> {
  try {
    const data = await fetchJson<SynthesisResponse>(`/api/bark/jobs/${jobId}`);
    return {
      id: data.job_id,
      status: data.status,
      plan: data.plan,
      artifacts: data.artifacts,
      progress: data.status === 'completed' ? 100 : 50,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      prompt: ''
    };
  } catch (error) {
    console.warn('Job polling unavailable:', error);
    return null;
  }
}

export async function fetchAudioBlob(url: string): Promise<Blob> {
  const response = await fetch(url);
  if (!response.ok) throw new Error('Unable to fetch audio');
  return response.blob();
}

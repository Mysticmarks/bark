export type HealthResponse = {
  status: string;
  time: string;
  version: string;
};

export type CapabilityResponse = {
  modalities: string[];
  video_presets: Record<string, [number, number]>;
  audio_bitrates: string[];
  codecs: Record<string, string>;
  notes: string[];
};

export type SynthesisPlan = {
  prompt_length: number;
  modalities: string[];
  render_video: boolean;
  dry_run: boolean;
  video_overrides?: Record<string, unknown> | null;
  routing_priorities?: Record<string, number>;
};

export type SynthesisResponse = {
  job_id: string;
  status: 'planned' | 'queued' | 'running' | 'completed' | 'failed';
  plan: SynthesisPlan;
  artifacts: Record<string, string>;
};

export type JobState = {
  id: string;
  status: SynthesisResponse['status'];
  plan: SynthesisPlan;
  artifacts: Record<string, string>;
  progress: number;
  createdAt: number;
  updatedAt: number;
  prompt: string;
};

export type ToastKind = 'info' | 'success' | 'error';

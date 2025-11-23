# Omnimodal Bark Expansion Plan

This document outlines a concrete roadmap for evolving Bark from text-to-audio into a fully omnimodal generation stack that can jointly reason over text, audio, images, and structured control signals.

## Objectives
- **Unified encoder**: add lightweight modality adapters (audio, text, image, control) that project into a shared semantic space without retraining the core decoder from scratch.
- **Composable conditioning**: allow multiple simultaneous prompts (e.g., text + reference audio + sketch image) to steer generation.
- **Latency-aware inference**: maintain near-real-time synthesis for speech-centric paths while enabling slower high-fidelity branches for music or soundscapes.
- **Responsible use**: introduce guardrails for unsafe content and watermarking hooks for generated media.

## Architecture Sketch
1. **Modality adapters**
   - **Text**: reuse existing tokenizer and positional scheme; add optional instruction-tuning prefix for style control.
   - **Audio**: integrate a pretrained self-supervised encoder (e.g., EnCodec embeddings) to provide style or continuation cues.
   - **Image**: use a frozen vision encoder (CLIP/ViT) with a projection head to align image embeddings to Bark's semantic space; enables audio-from-image use cases.
   - **Control tokens**: reserve IDs for beat markers, phoneme hints, or SFX triggers to support fine-grained editing.
2. **Fusion block**
   - Concatenate modality embeddings with learned type tags.
   - Apply cross-attention into the existing Bark decoder, gated by a routing MLP that can down-weight missing modalities.
3. **Decoder extensions**
   - Keep the current audio decoder; add optional diffusion upsampler head for higher bitrate outputs.
   - Provide a small adapter layer so legacy checkpoints remain compatible.

## Data & Training Pipeline
- **Datasets**: mix text-speech pairs, sound effects libraries with captions, and curated image–audio pairs; ensure multilingual coverage.
- **Sampling**: temperature-scaled curriculum to balance speech vs. music vs. Foley.
- **Augmentations**: loudness jitter, room impulse responses, time-stretch for robustness; for images, standard crop/flip/color jitter.
- **Losses**: combine reconstruction loss on audio tokens with contrastive alignment losses between modalities.

## Inference API Proposal
- Extend `generate_audio` signature to accept:
  ```python
  generate_audio(
      text: str | None = None,
      reference_audio: np.ndarray | None = None,
      image: np.ndarray | None = None,
      control_events: list[ControlEvent] | None = None,
      **kwargs,
  )
  ```
- Add a `ModalityBundle` dataclass to encapsulate normalized inputs and routing metadata.
- Support prioritized routing (e.g., prefer reference audio prosody over text punctuation).

## Evaluation
- **Speech**: MOS and ASR WER on multilingual benchmarks.
- **Music/Foley**: FAD, CLAP score, and human preference studies.
- **Safety**: prompt blocklist coverage and watermark detectability rate.

## Milestones
1. **Prototype adapters**: plug-and-play modality projections; verify backward compatibility.
2. **Fusion training**: multi-modal alignment with small datasets to validate routing behavior.
3. **Latency tuning**: profile cross-attention overhead; add knobs for adapter skipping.
4. **Public preview**: gated release with watermarking and opt-in telemetry for quality signals.

## Open Questions
- How to best share parameters between music and speech without regression?
- Should image conditioning be global (scene-aware soundscape) or local (per-region audio cues)?
- What watermarking scheme balances robustness and imperceptibility for long-form audio?

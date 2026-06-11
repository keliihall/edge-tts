# Local TTS Evaluation Source Notes

Generated: 2026-06-11

## Decision Frame

The scorecard answers a product decision for ShengJian: which locally deployable
TTS backends are worth integrating behind the existing Flask task workflow.
The primary audience is product and engineering stakeholders.

The weighted product score is:

- Chinese quality and robustness: 25%
- Product capability fit: 15%
- Local deployment cost: 15%
- Integration and serving maturity: 15%
- License and commercial clarity: 15%
- Ecosystem and maintenance: 10%
- Cross-platform and offline packaging: 5%

Scores are desk-research estimates on a 1-10 scale. They are not listening-test
results. Hardware bands are planning estimates inferred from model size,
precision, auxiliary components, and documented serving paths. They must be
replaced with measurements on target machines during the proof of concept.

## Current Product Evidence

- `app.py:110` uses one process-wide worker, which is compatible with serialized
  GPU inference but should call a persistent model sidecar rather than load a
  model for every task.
- `app.py:511-516` validates one global Edge voice-id namespace.
- `app.py:1005-1072` stores voice and four Edge-specific controls in each job.
- `app.py:1134-1141` calls the Edge-specific generation function directly.
- `app.py:1605-1663` and `app.py:2130-2189` require network connectivity before
  preview or conversion, which blocks an offline provider.
- `app.py:1679-1764` contains the current hard-wired Edge TTS adapter.
- `app.py:704-721` creates MP3-only temporary files and concatenates audio bytes.
  Most local engines emit WAV, so a canonical PCM merge/transcode stage is
  required before supporting multiple providers safely.
- `requirements.txt` contains only Flask, edge-tts, and pytest. PyTorch model
  stacks should not be folded into the current single-file PyInstaller bundle.

## Primary Sources

### CosyVoice 3

- Official repository: https://github.com/FunAudioLLM/CosyVoice
- Official model: https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512
- License: https://github.com/FunAudioLLM/CosyVoice/blob/main/LICENSE
- Evidence used: 0.5B release, nine languages, 18+ Chinese dialects/accents,
  pronunciation control, text/audio bi-streaming, approximately 150 ms claimed
  latency, FastAPI and accelerated serving paths, Apache-2.0 metadata.

### Qwen3-TTS

- Official repository: https://github.com/QwenLM/Qwen3-TTS
- Official 1.7B base model: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base
- Evidence used: 0.6B and 1.7B variants, ten languages, voice cloning, custom
  voices, voice design, streaming, instruction control, Apache-2.0, and official
  Seed-TTS benchmark tables.

### Chatterbox

- Official repository: https://github.com/resemble-ai/chatterbox
- Mandarin V3 model: https://huggingface.co/ResembleAI/Chatterbox-Multilingual-zh-cmn
- Evidence used: 0.5B multilingual V3, dedicated Mandarin checkpoint, voice
  cloning, pip package, CPU/CUDA/MPS device options, MIT license.

### GPT-SoVITS

- Official repository: https://github.com/RVC-Boss/GPT-SoVITS
- Evidence used: five-second zero-shot cloning, one-minute few-shot training,
  Chinese/Cantonese/English/Japanese/Korean support, API and Docker paths,
  tested CUDA/CPU/Apple Silicon environments, official v2 ProPlus RTF claims.

### Spark-TTS

- Official repository: https://github.com/SparkAudio/Spark-TTS
- Evidence used: 0.5B model, Chinese/English, voice cloning, gender/pitch/rate
  controls, Apache-2.0, and official Triton/TensorRT-LLM serving example.

### Kokoro

- Official repository: https://github.com/hexgrad/kokoro
- Evidence used: 82M parameters, Mandarin pipeline, pip package, Apache-2.0
  code and weights, CPU and Apple Silicon paths.

### OpenVoice

- Official repository: https://github.com/myshell-ai/OpenVoice
- Evidence used: V2 Chinese support, cross-lingual cloning, style control, MIT
  license and explicit free commercial use statement.

### IndexTTS2

- Official repository: https://github.com/index-tts/index-tts
- License: https://github.com/index-tts/index-tts/blob/main/LICENSE
- Evidence used: 1.5B model, Chinese pinyin control, emotion/timbre
  disentanglement, duration control, custom license thresholds and restrictions.

### F5-TTS

- Official repository: https://github.com/SWivid/F5-TTS
- Evidence used: current releases, Chinese/English quality benchmarks and
  inference tooling. The repository states that code is MIT but pretrained
  weights are CC-BY-NC because of the training data.

### Piper

- Official repository: https://github.com/OHF-Voice/piper1-gpl
- Evidence used: CPU-first local engine, CLI/web/Python/C++ APIs, GPL-3.0,
  active 1.4.x release line, and per-voice licensing requirement.

### Fish Audio S2

- Official repository: https://github.com/fishaudio/fish-speech
- Official model: https://huggingface.co/fishaudio/s2-pro
- License: https://github.com/fishaudio/fish-speech/blob/main/LICENSE
- Evidence used: 4B/5B flagship model, 80+ languages, inline expression control,
  multi-speaker and multi-turn generation, official benchmark claims, H200
  serving figures, and separate-license requirement for commercial use.

## Chart Map

- `assets/product-score.png`: ranked horizontal bars; answers which candidates
  best balance quality, deployment, integration, and commercial constraints.
- `assets/capability-heatmap.png`: category heatmap; shows why role-specific
  candidates can rank differently from the quality leaders.

## Important Caveats

- Vendor benchmark tables use different datasets, prompts, reference audio, and
  inference settings. Cross-project numbers are directional rather than fully
  comparable.
- No candidate has yet been run on the product's target Windows, macOS, and Linux
  machines.
- Voice cloning requires consent, provenance, abuse controls, and watermark or
  audit decisions in addition to model licensing.
- A legal review is still required before commercial distribution, especially
  for model weights, bundled checkpoints, generated-output terms, and copyleft
  dependencies.

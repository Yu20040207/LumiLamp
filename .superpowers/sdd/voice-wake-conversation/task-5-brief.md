# Task 5: sherpa-onnx Wake-Word Adapter

Implement only Task 5 from the approved plan. Dependency/model installation is already explicitly approved and complete.

Files: `pyproject.toml` already updated; create `src/lumilamp/voice/wakeword.py`, `tests/test_wakeword.py`, `configs/wakeword.example.yaml`; modify `README.md` only for wake configuration/operator notes.

Model directory: `/home/lamp/.cache/lumilamp/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`.

Interfaces:

- `WakeWordConfig(model_dir: Path, keyword: str = "你好露米", threshold: float = 0.25, score: float = 1.0)`
- `SherpaWakeWordDetector(config)` with `accept_pcm(samples: array[int]) -> bool` and `reset() -> None`.

Requirements:

- Strict TDD and report RED/GREEN.
- Importing module must not import/load sherpa model or open microphone.
- Validate config and explicit encoder/decoder/joiner/tokens paths.
- Lazily import `sherpa_onnx` inside detector construction.
- Generate a keyword token file for exact `你好露米` with the official model text2token procedure; preserve generated file and document it.
- Convert signed int16 samples to normalized floats for 16 kHz recognizer input.
- Do not log/store PCM or credentials.
- Unit tests fake sherpa boundary and never use microphone/network.
- After unit tests, load real local model and feed an official bundled WAV fixture through `accept_pcm`; no cloud/device access.
- Update example config and concise README notes, no secrets.
- Run focused/full tests and compileall.
- No device I/O, network calls beyond already completed model download, secrets, hardware control, further installs, deletes, Git commits, or subagents.
- Report `.superpowers/sdd/voice-wake-conversation/task-5-report.md`, including resolved versions and local fixture result.


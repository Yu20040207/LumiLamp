# Voice Wake Conversation SDD Ledger

- Workspace: `/home/lamp/project/LumiLamp` (in-place; `git` is unavailable and project rules prohibit commits)
- Plan: `docs/superpowers/plans/2026-08-26-voice-wake-conversation.md`
- Baseline: 12 tests passed on 2026-08-26
- Preflight ruling: use task-scoped snapshot diffs instead of Git review packages; cost if wrong: reviewers may have less repository-history context, mitigated by explicit before/after files and focused task scope.

## Shared interfaces

| Task | Consumes | Produces | Status |
|---|---|---|---|
| 1 | `VoiceConfig.ark_api_key`, `VoiceConfig.ark_model_id` | Ark request builder, response parser, text client | complete |
| 2 | TTS WAV path | validated ALSA volume/playback helpers | complete |
| 3 | ALSA capture device | endpointed utterance WAV or no-speech result | complete |
| 4 | injected clock/random chooser | pure conversation state machine | complete |
| 5 | local PCM and sherpa model | offline wake detection | in progress; dependency/model approved and installed |
| 6 | adapters above | half-duplex orchestration | pending |
| 7 | CLI arguments/config | runnable voice command | pending |
| 8 | approved live devices | staged audio validation | pending approval |

- Task 1: fix round 1/5 (4 findings addressed, 0 open; no Git commits)
- Task 1: offline implementation complete (independent review clean; 9 focused and 21 full-suite tests passed)
- Task 1: cloud integration probe pending explicit approval because it sends text externally and consumes Ark quota.
- Task 1: approved Ark cloud probe succeeded; only assistant text was printed and no credential was exposed.
- Task 1: complete (no Git commits, review clean, cloud probe successful)
- Task 2: complete (no Git commits, review clean; 9 focused and 28 full-suite tests passed)
- Task 3: complete (no Git commits, review approved; 8 focused/legacy and 35 full-suite tests passed)
- Task 3: deferred minor: non-little-endian PCM branch lacks direct test; no effect on current little-endian Raspberry Pi, but portability regression coverage is weaker.
- Task 4: complete (no Git commits, review approved; 8 focused and 43 full-suite tests passed)
- Task 4: deferred minors: incomplete invalid-transition matrix coverage and no automated forbidden-import purity guard; implementation was source-reviewed as correct and pure.
- Task 5: user approved dependency/model installation. Dry-run found cp313 aarch64 wheels; installed sherpa-onnx 1.13.6 and core 1.13.6 in `.venv`.
- Task 5: official zh-en 3M KWS archive downloaded and preserved under `/home/lamp/.cache/lumilamp/models/`; extracted files listed before model loading.

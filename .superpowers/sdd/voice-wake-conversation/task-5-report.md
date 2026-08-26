# Task 5 Report: sherpa-onnx Wake-Word Adapter

## Implementation

- Added `WakeWordConfig` for the exact approved phrase `你好露米`, with finite
  threshold/score validation.
- Added `SherpaWakeWordDetector`, which validates explicit encoder, decoder,
  joiner, tokens, and keyword-token paths before lazily importing sherpa-onnx.
- The detector converts `array('h')` signed int16 samples to float PCM using
  `sample / 32768.0`, feeds a 16 kHz streaming recognizer, decodes all ready
  frames, emits one Boolean wake event, and resets the stream after detection.
- Added the offline example configuration and concise privacy/operator notes.
- Preserved the exact ppinyin token line
  `n ǐ h ǎo l ù m ǐ @你好露米` as
  `/home/lamp/.cache/lumilamp/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/keywords_lumilamp.txt`.
  It follows the installed official `text2token` `ppinyin` procedure, and every
  emitted token was checked against the model's `tokens.txt`.

## Resolved local components

- Python: `3.13.5` (`aarch64`).
- `sherpa-onnx`: `1.13.6`.
- `sherpa-onnx-core`: `1.13.6`.
- Model: `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`.
- Preserved model archive: `32,885,699` bytes.
- Runtime paths: chunk-8 int8 encoder (`4,600,657` bytes), chunk-8 decoder
  (`759,829` bytes), chunk-8 int8 joiner (`86,629` bytes), and `tokens.txt`
  (`1,928` bytes).

The installed sherpa package exposes the official `text2token` implementation,
but its optional CLI helpers (`click`, `pypinyin`, and `sentencepiece`) are not
installed. No additional installation was performed. The generated exact-phrase
output was derived from that installed procedure and the model's `ppinyin`
format, then validated against the shipped token table.

## TDD evidence

1. Added the wake-word tests before production code.
2. RED: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_wakeword.py -v`
   failed with `ModuleNotFoundError: No module named 'lumilamp.voice.wakeword'`.
3. Added the minimum adapter implementation.
4. GREEN: the same focused command passed all 9 tests.

The tests cover the confirmed defaults, invalid configuration, import safety,
missing explicit model files, exact sherpa constructor arguments, signed-int16
normalization, decode readiness, one-shot detection/reset, explicit reset, and
wrong PCM array types. The sherpa boundary is replaced with an in-memory fake;
tests never open a microphone or make a network request.

## Verification

Static check:

- `.venv/bin/python -m compileall -q src tests` exited 0.
- The forbidden hardware-import scan for `RPi`, `gpiozero`, `serial`, `smbus`,
  and `spidev` was empty.
- Module import does not import sherpa-onnx, load an ONNX model, or access an
  audio device.

Code test:

- Focused wake-word suite: 9 tests passed.
- Full unittest discovery: 52 tests passed.
- Real local-model integration loaded the approved model and fed the bundled
  `test_wavs/zh_0.wav` fixture through `accept_pcm` in 1,600-sample chunks plus
  in-memory trailing silence. Fixture metadata was 16 kHz, mono, 16-bit,
  89,784 frames; result was `detected=False`, as this vendor fixture does not
  contain the LumiLamp wake phrase.
- No PCM was written or logged, and no cloud, microphone, speaker, credential,
  or network access occurred.

Physical-hardware validation:

- 未进行。No microphone, speaker, GPIO, serial, ESP32-S3, servo, or other
  physical hardware was accessed. The bundled-WAV run is software integration,
  not physical-hardware validation.

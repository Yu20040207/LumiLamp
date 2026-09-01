# LumiLamp

LumiLamp is a fixed desktop lamp robot intended to express emotion through
natural head, arm, and base motion. This repository is currently a
hardware-free simulation skeleton.

## Run the demo

No installation or third-party dependency is required:

```bash
cd /home/lamp/project/LumiLamp
PYTHONPATH=src python3 -m lumilamp.app --demo curious
```

## Run tests

```bash
cd /home/lamp/project/LumiLamp
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Run one-shot streaming ASR on Raspberry Pi

The command below captures one utterance from the LumiLamp USB microphone,
streams in-memory PCM to Doubao Streaming ASR 2.0, displays partial text, and
prints the final transcript. It does not save a recording or start a
background service.

Create the ignored `.env.voice` file first and keep its permissions at `600`.
It must define `DOUBAO_APP_ID`, `DOUBAO_ACCESS_TOKEN`, and
`DOUBAO_ASR_RESOURCE_ID`.

```bash
cd /home/lamp/pixarlamp
python3 -m venv .venv
.venv/bin/python -m pip install 'websockets>=15,<16'
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.asr_cli
```

The CLI discovers the USB microphone by USB ID `08bb:2902` and uses a stable
ALSA card name instead of persisting a numeric card index. Use `--device` only
for an explicit temporary override. Running the command makes a real cloud
request and must remain a deliberate user action.

## Local wake-word configuration

`configs/wakeword.example.yaml` records the offline sherpa-onnx defaults for
the approved wake phrases `露米` and `你好露米`. The detector accepts 16 kHz
signed 16-bit mono PCM supplied by its caller, returns the matched phrase, and
does not load a model or open a microphone on import.

Prepare the official local KWS model explicitly; the command refuses to
overwrite its destination and does not download anything until it is run:

```bash
.venv/bin/python -m pip install -e '.[kws-tools]'
mkdir -p models/kws
PATH="$PWD/.venv/bin:$PATH" scripts/prepare_kws_model.sh \
  models/kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
```

The preparation step writes raw labelled phrases (`露米 @露米` and
`你好露米 @你好露米`) and uses the model's `phone+ppinyin` tokenization with its
`en.phone` lexicon. The published `keywords_lumilamp.txt` therefore contains
only model vocabulary tokens plus the exact terminal labels `@露米` and
`@你好露米`; it never treats Chinese characters as model tokens. Every phoneme
token is verified against the downloaded `tokens.txt` before copying the
model. Wake-listening PCM stays in memory and is not logged, stored, or sent
to a cloud service.

## Validate the interactive voice loop

First create the ignored, mode-`0600` `/home/lamp/pixarlamp/.env.voice` file.
In addition to the ASR settings above, it must define
`DOUBAO_TTS_API_KEY`, `DOUBAO_TTS_RESOURCE_ID`, `ARK_API_KEY`,
`ARK_MODEL_ID`, `LUMILAMP_KWS_MODEL_DIR`, and `LUMILAMP_WAKE_CACHE_DIR`.
Prepare the KWS model plus four wake-reply WAV files and one fixed offline
network-interruption WAV with the explicit setup
scripts before validation.

Run the static dry-run first:

```bash
cd /home/lamp/pixarlamp
PYTHONPATH=src .venv/bin/python -m lumilamp.voice.voice_cli \
  --config /home/lamp/pixarlamp/.env.voice \
  --dry-run
```

The dry-run reads and validates the configuration, required KWS files, wake
cache, USB microphone and speaker identities, and Python dependency imports.
It does not start `arecord`, open WebSockets or HTTP requests, synthesize
speech, run `aplay`, or change the ALSA mixer.

The interactive path uses Ark text streaming and starts TTS only after a
complete short Chinese sentence is available. It remains half-duplex: the
microphone is not opened while a response is streaming or playing. A terminal
line records only phase durations (`asr`, `ark_first_sentence`, `first_audio`,
`answer_complete`, and `total`), never recognized text or credentials. If the
Ark stream ends unexpectedly, already played sentences remain played and the
prepared local `网络好像断开了` WAV is attempted once; no complete-answer retry
is made.

Removing `--dry-run` starts the real microphone, local wake-word detector,
cloud ASR, Ark and TTS services, and USB speaker playback. Do that only as an
explicitly announced physical-audio and cloud validation step. The voice-loop
command does not upload ESP32 firmware and does not access or validate servos.

Before a first streaming runtime validation, obtain separate confirmation for
each external action in this order: generate the new cached network-error WAV
with the TTS quota, run the dry-run, send one Ark streaming request with the
Ark quota, then perform one USB microphone/speaker latency run. None of these
steps operate an ESP32 or any servo.

## Safety boundary

Motion output remains simulation-only. `MockBus` records commands in memory
and never opens GPIO, serial, camera, or network devices. The explicitly run
voice CLI is separate from motion control. Real motor output must remain
unavailable until hardware wiring, independent motor power, common ground,
limits, emergency stop, and a safe pose are confirmed.

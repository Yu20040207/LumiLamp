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

## Local wake-word configuration

`configs/wakeword.example.yaml` records the offline sherpa-onnx defaults for
the exact wake phrase `你好露米`. The detector accepts 16 kHz signed 16-bit
mono PCM supplied by its caller; importing the module does not load the model
or open a microphone.

The approved model directory contains the preserved generated token file
`keywords_lumilamp.txt`. Its line is `n ǐ h ǎo l ù m ǐ @你好露米`, the
output of sherpa-onnx's `text2token` procedure with `tokens-type=ppinyin` for
the raw line `你好露米 @你好露米`. Wake-listening PCM stays in memory and is
not logged, stored, or sent to a cloud service.

## Safety boundary

Simulation is the only implemented mode. `MockBus` records commands in
memory and never opens GPIO, serial, camera, or network devices. Real motor
output must remain unavailable until hardware wiring, independent motor
power, common ground, limits, emergency stop, and a safe pose are confirmed.

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

## Safety boundary

Simulation is the only implemented mode. `MockBus` records commands in
memory and never opens GPIO, serial, camera, or network devices. Real motor
output must remain unavailable until hardware wiring, independent motor
power, common ground, limits, emergency stop, and a safe pose are confirmed.


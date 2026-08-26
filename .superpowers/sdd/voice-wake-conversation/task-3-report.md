# Task 3 Report: Utterance Capture and Silence Endpointing

## Implementation

- Added `LevelConfig`, normalized signed-16-bit PCM RMS calculation, and pure endpointing logic.
- Added `record_utterance`, which starts only its own `arecord` child with a no-shell argument list, reads 640-byte (20 ms) PCM chunks, and writes a mono 16 kHz WAV only after speech begins.
- The recorder ends at 800 ms trailing silence or 10 seconds total, returns `False` without opening a WAV when speech never starts, and terminates/waits only for the child it created.
- Preserved the existing fixed-duration `record_wav` API.

## TDD evidence

1. Endpoint tests were added first and failed with `ImportError: cannot import name 'LevelConfig'`.
2. After the minimal endpoint implementation, the focused test command passed 3 tests.
3. RMS tests were added next and failed with `ImportError: cannot import name 'pcm_level'`.
4. After the RMS implementation, the focused test command passed 5 tests.
5. Streaming-capture tests were added next and failed with `ImportError: cannot import name 'record_utterance'`.
6. After the streaming implementation, the focused test command passed 7 tests.
7. The leading-silence regression test was run against an intentional temporary mutation that retained pre-threshold PCM; it failed at the WAV frame assertion. Restoring the threshold gate returned the focused suite to green.

## Verification

Static check:

- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests` exited 0.
- Reviewed `recorder.py`: it uses `array('h')`, explicitly byte-swaps on non-little-endian hosts, and contains no NumPy, PyAudio, shell execution, broad process-kill command, cloud call, or hardware-control path.

Code test:

- `PYTHONPATH=src .venv/bin/python -m unittest tests/test_utterance_recorder.py -v` passed 7 tests.
- `PYTHONPATH=src .venv/bin/python -m unittest tests/test_voice_recorder.py -v` passed 1 test.
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v` passed 35 tests.
- Capture tests replace `subprocess.Popen` with an in-memory fake process and replace WAV output with a mock writer; no microphone was opened.

Physical-hardware validation:

- 未进行。No microphone, speaker, GPIO, serial, servo, or other physical hardware was accessed.

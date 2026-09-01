### Task 10: Explicit Cloud and Physical Audio Validation

**Files:**
- Generated only in ignored cache/output paths; no source changes expected unless a diagnosed defect requires a new TDD fix cycle.

**Interfaces:**
- Consumes: separate user confirmation immediately before quota-consuming/cloud or audible tests.
- Produces evidence: Ark response, TTS cache, both wake phrases, two-turn loop, idle timeout, and failure behavior.

- [ ] **Step 1: Run one redacted Ark text probe**

Load `.env.voice` without printing it, ask a short fixed question, and print only model ID, elapsed time, request outcome, and assistant text. Do not print request headers.

- [ ] **Step 2: Generate and validate four wake-reply WAV files**

Run `scripts/prepare_wake_replies.py` with explicit config/cache paths. Validate all four WAV headers and report filenames, durations, and sample format. This proves cloud TTS output generation, not speaker playback.

- [ ] **Step 3: Play each cached reply through the resolved USB speaker**

Resolve USB ID `1b3f:2008`, set the confirmed safe volume, play one file at a time, and ask the user to confirm audibility. This proves physical speaker playback only.

- [ ] **Step 4: Validate both local wake phrases**

With cloud conversation disabled, open USB microphone `08bb:2902` and test `露米` and `你好露米` separately at close range. Report matched phrase and latency; do not save PCM.

- [ ] **Step 5: Run the complete half-duplex loop**

Start the CLI, wake it, complete at least two turns without repeating the wake phrase, verify the random acknowledgement, ASR text, Ark answer, TTS playback, no self-recognition during playback, and microphone resume after approximately 300 ms.

- [ ] **Step 6: Validate timeout and cleanup**

Leave the session idle for 30 seconds, confirm silent sleep, then stop with Ctrl-C and verify no owned `arecord`, `aplay`, or voice-loop process remains.

- [ ] **Step 7: Final verification report**

Report these independently:

- Environment installation
- Static check
- Code test
- Cloud ASR validation
- Cloud Ark validation
- Cloud TTS validation
- USB microphone/KWS validation
- USB speaker validation
- Complete voice-loop validation
- Firmware upload: not executed
- ESP32/servo physical validation: not executed
- Installed-system validation: only claim if the complete loop was run on the target Raspberry Pi in its intended setup

Do not treat any earlier category as proof of a later one. Do not commit or push unless separately authorized.

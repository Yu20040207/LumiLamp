# Architecture

The Raspberry Pi owns perception, voice, AI decisions, motion planning, and
logs. The ESP32-S3 owns real-time motor communication and safety. Raspberry Pi
software remains simulation-first until the USB command protocol is implemented
and validated. The current physical I/O path is limited to the standalone,
single-servo ESP32-S3 bench firmware under `firmware/esp32/sts3215_test/`.


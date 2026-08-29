# Hardware plan

The Raspberry Pi 4B owns perception, voice, AI, and motion decisions. The
ESP32-S3 N16R8 owns the 1 Mbps Feetech STS3215 bus, safety checks, and real-time
motion execution. Their first integration path is native USB CDC; detect the
actual device and prefer `/dev/serial/by-id/` over a hard-coded tty name.

The verified single-servo bench uses an ST-3215-C018 (ID 1), URT-2, and an
independent 12 V / 3 A servo supply. The bench firmware is under
`firmware/esp32/sts3215_test/`. Small relative moves and telemetry have been
physically verified; mechanical limits, multiple joints, emergency-stop input,
and installed-system behavior remain unverified.


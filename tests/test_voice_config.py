import tempfile
import unittest
from pathlib import Path

from lumilamp.voice.config import (
    AsrConfig,
    VoiceConfig,
    load_asr_config,
    load_voice_config,
)


class VoiceConfigTests(unittest.TestCase):
    def test_loads_asr_only_settings_without_exposing_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.voice"
            env_file.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-123",
                        "DOUBAO_ACCESS_TOKEN=private-token",
                        "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration",
                    )
                ),
                encoding="utf-8",
            )

            config = load_asr_config(env_file)

        self.assertIsInstance(config, AsrConfig)
        self.assertEqual(config.app_id, "app-123")
        self.assertEqual(config.resource_id, "volc.seedasr.sauc.duration")
        self.assertNotIn("private-token", repr(config))

    def test_asr_only_settings_require_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.voice"
            env_file.write_text(
                "DOUBAO_APP_ID=app-123\n"
                "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "DOUBAO_ACCESS_TOKEN"):
                load_asr_config(env_file)

    def test_rejects_legacy_positional_config_before_it_can_mix_credentials(self) -> None:
        with self.assertRaises(TypeError):
            VoiceConfig(
                "app-123",
                "asr-secret",
                "volc.seedasr.sauc.duration",
                "seed-tts-2.0",
                "ark-secret",
                "doubao-seed-2-0-lite-260428",
            )

    def test_loads_tts_api_key_without_exposing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-123",
                        "DOUBAO_ACCESS_TOKEN=token-value",
                        "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration",
                        "DOUBAO_TTS_API_KEY=tts-secret",
                        "DOUBAO_TTS_RESOURCE_ID=seed-tts-2.0",
                        "ARK_API_KEY=ark-secret",
                        "ARK_MODEL_ID=doubao-seed-2-0-lite-260428",
                        "LUMILAMP_KWS_MODEL_DIR=/opt/lumilamp/models/kws",
                        "LUMILAMP_WAKE_CACHE_DIR=/opt/lumilamp/cache/wake",
                    )
                ),
                encoding="utf-8",
            )

            config = load_voice_config(env_file)

        self.assertEqual(config.asr.app_id, "app-123")
        self.assertEqual(config.asr.resource_id, "volc.seedasr.sauc.duration")
        self.assertEqual(config.tts_api_key, "tts-secret")
        self.assertEqual(config.tts_resource_id, "seed-tts-2.0")
        self.assertEqual(config.ark_model_id, "doubao-seed-2-0-lite-260428")
        self.assertEqual(config.kws_model_dir, Path("/opt/lumilamp/models/kws"))
        self.assertEqual(config.wake_cache_dir, Path("/opt/lumilamp/cache/wake"))
        self.assertNotIn("token-value", repr(config))
        self.assertNotIn("tts-secret", repr(config))
        self.assertNotIn("ark-secret", repr(config))

    def test_loads_optional_esp32_stable_serial_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-123",
                        "DOUBAO_ACCESS_TOKEN=asr-secret",
                        "DOUBAO_ASR_RESOURCE_ID=asr-resource",
                        "DOUBAO_TTS_API_KEY=tts-secret",
                        "DOUBAO_TTS_RESOURCE_ID=tts-resource",
                        "ARK_API_KEY=ark-secret",
                        "ARK_MODEL_ID=ark-model",
                        "LUMILAMP_KWS_MODEL_DIR=/opt/models",
                        "LUMILAMP_WAKE_CACHE_DIR=/opt/cache",
                        "LUMILAMP_ESP32_SERIAL_BY_ID=/dev/serial/by-id/usb-Espressif-if00",
                    )
                ),
                encoding="utf-8",
            )

            config = load_voice_config(env_file)

        self.assertEqual(
            config.esp32_serial_by_id,
            Path("/dev/serial/by-id/usb-Espressif-if00"),
        )

    def test_rejects_tty_acm_as_esp32_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-123",
                        "DOUBAO_ACCESS_TOKEN=asr-secret",
                        "DOUBAO_ASR_RESOURCE_ID=asr-resource",
                        "DOUBAO_TTS_API_KEY=tts-secret",
                        "DOUBAO_TTS_RESOURCE_ID=tts-resource",
                        "ARK_API_KEY=ark-secret",
                        "ARK_MODEL_ID=ark-model",
                        "LUMILAMP_KWS_MODEL_DIR=/opt/models",
                        "LUMILAMP_WAKE_CACHE_DIR=/opt/cache",
                        "LUMILAMP_ESP32_SERIAL_BY_ID=/dev/ttyACM0",
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "serial.*by-id"):
                load_voice_config(env_file)

    def test_rejects_missing_tts_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-123",
                        "DOUBAO_ACCESS_TOKEN=asr-secret",
                        "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration",
                        "DOUBAO_TTS_RESOURCE_ID=seed-tts-2.0",
                        "ARK_API_KEY=ark-secret",
                        "ARK_MODEL_ID=doubao-seed-2-0-lite-260428",
                        "LUMILAMP_KWS_MODEL_DIR=/opt/lumilamp/models/kws",
                        "LUMILAMP_WAKE_CACHE_DIR=/opt/lumilamp/cache/wake",
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "DOUBAO_TTS_API_KEY"):
                load_voice_config(env_file)

    def test_rejects_missing_required_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text("DOUBAO_APP_ID=app-123\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "DOUBAO_ACCESS_TOKEN"):
                load_voice_config(env_file)


if __name__ == "__main__":
    unittest.main()

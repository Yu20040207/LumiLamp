import os
import tempfile
import unittest
from pathlib import Path

from lumilamp.voice.config import VoiceConfig, load_voice_config


class VoiceConfigTests(unittest.TestCase):
    def test_loads_required_cloud_settings_without_exposing_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-123",
                        "DOUBAO_ACCESS_TOKEN=token-value",
                        "DOUBAO_ASR_RESOURCE_ID=volc.seedasr.sauc.duration",
                        "DOUBAO_TTS_RESOURCE_ID=seed-tts-2.0",
                        "ARK_API_KEY=ark-value",
                        "ARK_MODEL_ID=doubao-seed-2-0-lite-260428",
                    )
                ),
                encoding="utf-8",
            )

            config = load_voice_config(env_file)

        self.assertEqual(config.app_id, "app-123")
        self.assertEqual(config.asr_resource_id, "volc.seedasr.sauc.duration")
        self.assertEqual(config.tts_resource_id, "seed-tts-2.0")
        self.assertEqual(config.ark_model_id, "doubao-seed-2-0-lite-260428")
        self.assertNotIn("token-value", repr(config))
        self.assertNotIn("ark-value", repr(config))

    def test_rejects_missing_required_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "voice.env"
            env_file.write_text("DOUBAO_APP_ID=app-123\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "DOUBAO_ACCESS_TOKEN"):
                load_voice_config(env_file)


if __name__ == "__main__":
    unittest.main()

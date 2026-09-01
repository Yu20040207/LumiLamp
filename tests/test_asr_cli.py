import io
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lumilamp.voice.asr_cli import main
from lumilamp.voice.config import AsrConfig


class AsrCliTests(unittest.TestCase):
    @patch("lumilamp.voice.asr_cli.recognize_microphone", new_callable=AsyncMock)
    @patch("lumilamp.voice.asr_cli.discover_alsa_capture_device")
    @patch("lumilamp.voice.asr_cli.load_asr_config")
    def test_discovers_device_and_prints_partial_and_final_text(
        self, load_config, discover, recognize
    ) -> None:
        config = AsrConfig("app", "private-token", "resource")
        load_config.return_value = config
        discover.return_value = "plughw:CARD=Microphone,DEV=0"

        async def recognize_with_partial(*args):
            args[-1]("你好")
            return "你好露米"

        recognize.side_effect = recognize_with_partial
        output = io.StringIO()

        with patch("sys.stdout", output):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        load_config.assert_called_once_with(Path(".env.voice"))
        discover.assert_called_once_with()
        levels = recognize.await_args.args[2]
        self.assertEqual(levels.start_threshold, 0.02)
        self.assertEqual(levels.silence_threshold, 0.018)
        self.assertIn("识别中: 你好", output.getvalue())
        self.assertIn("识别结果: 你好露米", output.getvalue())
        self.assertNotIn("private-token", output.getvalue())

    @patch("lumilamp.voice.asr_cli.recognize_microphone", new_callable=AsyncMock)
    @patch("lumilamp.voice.asr_cli.discover_alsa_capture_device")
    @patch("lumilamp.voice.asr_cli.load_asr_config")
    def test_allows_explicit_device_override(
        self, load_config, discover, recognize
    ) -> None:
        load_config.return_value = AsrConfig("app", "token", "resource")
        recognize.return_value = "完成"

        exit_code = main(["--device", "plughw:CARD=Manual,DEV=0"])

        self.assertEqual(exit_code, 0)
        discover.assert_not_called()
        self.assertEqual(recognize.await_args.args[1], "plughw:CARD=Manual,DEV=0")

    @patch("lumilamp.voice.asr_cli.load_asr_config")
    def test_reports_safe_configuration_error(self, load_config) -> None:
        load_config.side_effect = ValueError(
            "missing required voice setting: DOUBAO_ACCESS_TOKEN"
        )
        error = io.StringIO()

        with patch("sys.stderr", error):
            exit_code = main([])

        self.assertEqual(exit_code, 1)
        self.assertIn("DOUBAO_ACCESS_TOKEN", error.getvalue())


if __name__ == "__main__":
    unittest.main()

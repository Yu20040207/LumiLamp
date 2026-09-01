import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from lumilamp.voice.wake_cache import (
    NETWORK_ERROR_REPLY,
    WAKE_REPLIES,
    WakeReplyCache,
)


def valid_wav_bytes(
    *, channels: int = 1, sample_width: int = 2, frame_rate: int = 24000, frames: bytes = b"\x00\x00"
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(sample_width)
        audio.setframerate(frame_rate)
        audio.writeframes(frames)
    return output.getvalue()


def write_valid_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(valid_wav_bytes())


class WakeReplyCacheTests(unittest.TestCase):
    def test_prepare_includes_network_error_reply_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(Path(directory))
            cache.prepare(lambda _text, path: write_valid_wav(path))

            self.assertEqual(NETWORK_ERROR_REPLY, "网络好像断开了")
            self.assertEqual(cache.path_for_error().name, "network-interrupted.wav")
            cache.validate()
    def test_maps_all_exact_replies_to_stable_names(self) -> None:
        cache = WakeReplyCache(Path("/cache"))

        self.assertEqual(
            {text: cache.path_for(text).name for text in WAKE_REPLIES},
            {
                "我在呀": "wo-zai-ya.wav",
                "你好呀": "ni-hao-ya.wav",
                "嗯？": "en.wav",
                "请吩咐": "qing-fen-fu.wav",
            },
        )

    def test_validate_accepts_complete_matching_manifest_and_wavs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(
                Path(directory), speaker="test-speaker", resource_id="test-resource"
            )
            cache.prepare(lambda _text, path: write_valid_wav(path))

            cache.validate()

    def test_validate_rejects_wav_with_wrong_sample_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(Path(directory))
            for text in WAKE_REPLIES:
                cache.path_for(text).write_bytes(valid_wav_bytes(frame_rate=16000))
            cache.manifest_path.write_text(
                json.dumps(cache.manifest()), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "24000"):
                cache.validate()

    def test_prepare_synthesizes_only_missing_or_invalid_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(Path(directory))
            existing = cache.path_for("我在呀")
            existing_bytes = valid_wav_bytes()
            existing.write_bytes(existing_bytes)
            cache.path_for("你好呀").write_bytes(b"not a wav")
            synthesized: list[tuple[str, Path]] = []

            def synthesize(text: str, path: Path) -> None:
                synthesized.append((text, path))
                write_valid_wav(path)

            cache.prepare(synthesize)

            self.assertEqual(existing.read_bytes(), existing_bytes)
            self.assertEqual(
                {text for text, _path in synthesized},
                {"你好呀", "嗯？", "请吩咐", NETWORK_ERROR_REPLY},
            )
            self.assertTrue(all(path.suffix == ".partial" for _text, path in synthesized))

    def test_prepare_preserves_existing_cache_when_synthesis_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(Path(directory))
            existing = cache.path_for("我在呀")
            existing_bytes = valid_wav_bytes(frames=b"\x01\x00")
            existing.write_bytes(existing_bytes)

            def synthesize(text: str, path: Path) -> None:
                if text == "你好呀":
                    raise RuntimeError("credential=value")
                write_valid_wav(path)

            with self.assertRaisesRegex(RuntimeError, "你好呀") as failure:
                cache.prepare(synthesize)

            self.assertNotIn("credential=value", str(failure.exception))
            self.assertEqual(existing.read_bytes(), existing_bytes)
            self.assertFalse(list(Path(directory).glob("*.partial")))

    def test_prepare_leaves_previous_manifest_when_a_later_synthesis_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(Path(directory))
            cache.prepare(lambda _text, path: write_valid_wav(path))
            previous_manifest = cache.manifest_path.read_bytes()
            cache.path_for("你好呀").write_bytes(b"invalid wav")
            cache.path_for("嗯？").write_bytes(b"invalid wav")

            def synthesize(text: str, path: Path) -> None:
                if text == "嗯？":
                    raise RuntimeError("credential=value")
                write_valid_wav(path)

            with self.assertRaisesRegex(RuntimeError, "嗯？"):
                cache.prepare(synthesize)

            self.assertEqual(cache.manifest_path.read_bytes(), previous_manifest)
            with self.assertRaises(ValueError):
                cache.validate()
            self.assertFalse(list(Path(directory).glob("*.partial")))

    def test_prepare_writes_manifest_with_exact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = WakeReplyCache(
                Path(directory), speaker="test-speaker", resource_id="test-resource"
            )
            cache.prepare(lambda _text, path: write_valid_wav(path))

            manifest = json.loads(cache.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["format_version"], 2)
            self.assertEqual(manifest["speaker"], "test-speaker")
            self.assertEqual(manifest["resource_id"], "test-resource")
            self.assertEqual(
                [entry["text"] for entry in manifest["replies"]],
                [*WAKE_REPLIES, NETWORK_ERROR_REPLY],
            )


class PrepareWakeRepliesCliTests(unittest.TestCase):
    def test_cli_uses_injected_synthesis_and_never_prints_config_secret(self) -> None:
        from scripts.prepare_wake_replies import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "voice.env"
            config_path.write_text(
                "\n".join(
                    (
                        "DOUBAO_APP_ID=app-id",
                        "DOUBAO_ACCESS_TOKEN=asr-secret",
                        "DOUBAO_ASR_RESOURCE_ID=asr-resource",
                        "DOUBAO_TTS_API_KEY=tts-secret",
                        "DOUBAO_TTS_RESOURCE_ID=tts-resource",
                        "ARK_API_KEY=ark-secret",
                        "ARK_MODEL_ID=ark-model",
                        "LUMILAMP_KWS_MODEL_DIR=/tmp/kws",
                        "LUMILAMP_WAKE_CACHE_DIR=/tmp/unused-cache",
                    )
                ),
                encoding="utf-8",
            )
            synthesized: list[str] = []
            output = io.StringIO()

            def synthesize(text: str, path: Path) -> None:
                synthesized.append(text)
                write_valid_wav(path)

            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                status = main(
                    ["--config", str(config_path), "--output-dir", str(root / "wake")],
                    synthesize=synthesize,
                )

            self.assertEqual(status, 0)
            self.assertEqual(synthesized, [*WAKE_REPLIES, NETWORK_ERROR_REPLY])
            self.assertIn("success", output.getvalue())
            self.assertNotIn("tts-secret", output.getvalue())
            self.assertNotIn("asr-secret", output.getvalue())

            second_output = io.StringIO()
            with contextlib.redirect_stdout(second_output), contextlib.redirect_stderr(second_output):
                second_status = main(
                    ["--config", str(config_path), "--output-dir", str(root / "wake")],
                    synthesize=lambda _text, _path: self.fail("existing cache was synthesized"),
                )

            self.assertEqual(second_status, 0)
            self.assertIn("success", second_output.getvalue())


if __name__ == "__main__":
    unittest.main()

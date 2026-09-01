import asyncio
import unittest

from lumilamp.voice.streaming_reply import StreamingReplyError, stream_and_play


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class StreamingReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_producer_continues_while_first_sentence_is_playing(self) -> None:
        first_play_started = asyncio.Event()
        second_produced = asyncio.Event()
        release_first_play = asyncio.Event()
        spoken: list[str] = []

        async def deltas():
            yield "第一句。"
            await first_play_started.wait()
            second_produced.set()
            yield "第二句。"

        async def speak(sentence: str) -> None:
            spoken.append(sentence)
            if sentence == "第一句。":
                first_play_started.set()
                await release_first_play.wait()

        task = asyncio.create_task(stream_and_play(deltas(), speak, FakeClock()))
        await first_play_started.wait()
        await asyncio.wait_for(second_produced.wait(), timeout=0.2)
        release_first_play.set()
        result = await task

        self.assertEqual(spoken, ["第一句。", "第二句。"])
        self.assertEqual(result.full_text, "第一句。第二句。")
        self.assertEqual(result.sentences_played, 2)

    async def test_propagates_playback_failure_without_playing_later_sentences(self) -> None:
        spoken: list[str] = []

        async def deltas():
            yield "第一句。第二句。"

        async def speak(sentence: str) -> None:
            spoken.append(sentence)
            raise RuntimeError("speaker detail must not leak")

        with self.assertRaisesRegex(StreamingReplyError, "tts_playback") as caught:
            await stream_and_play(deltas(), speak, FakeClock())

        self.assertEqual(spoken, ["第一句。"])
        self.assertNotIn("speaker detail", str(caught.exception))

    async def test_rejects_stream_without_any_sentence(self) -> None:
        async def deltas():
            if False:
                yield "never"

        async def speak(_: str) -> None:
            self.fail("empty stream must not play audio")

        with self.assertRaisesRegex(StreamingReplyError, "ark"):
            await stream_and_play(deltas(), speak, FakeClock())


if __name__ == "__main__":
    unittest.main()

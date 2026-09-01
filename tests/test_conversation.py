import unittest

from lumilamp.voice.conversation import ConversationController, WAKE_REPLIES
from lumilamp.voice.state import ConversationState
from lumilamp.voice.wake_cache import WAKE_REPLIES as CACHED_WAKE_REPLIES


class MutableClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.controller = ConversationController(
            clock=self.clock, choose=lambda replies: replies[2]
        )

    def test_reexports_the_cache_backed_exact_wake_replies(self) -> None:
        self.assertEqual(
            WAKE_REPLIES,
            ("我在呀", "你好呀", "嗯？", "请吩咐"),
        )
        self.assertIs(WAKE_REPLIES, CACHED_WAKE_REPLIES)

    def test_wake_selects_response_then_observes_playback_guard(self) -> None:
        self.assertEqual(self.controller.wake(), "嗯？")
        self.assertEqual(self.controller.state, ConversationState.WAKING)

        self.clock.now = 10.0
        self.controller.finish_playback()
        self.clock.now = 10.299
        self.assertFalse(self.controller.ready_after_playback())
        self.assertEqual(self.controller.state, ConversationState.WAKING)
        self.clock.now = 10.300
        self.assertTrue(self.controller.ready_after_playback())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)

    def test_wake_passes_all_confirmed_replies_to_chooser(self) -> None:
        chosen_from: list[tuple[str, ...]] = []
        controller = ConversationController(
            clock=self.clock,
            choose=lambda replies: chosen_from.append(replies) or replies[0],
        )

        self.assertEqual(controller.wake(), "我在呀")
        self.assertEqual(
            chosen_from,
            [("我在呀", "你好呀", "嗯？", "请吩咐")],
        )

    def test_begin_methods_follow_the_active_turn_sequence(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()

        self.controller.begin_recognition()
        self.assertEqual(self.controller.state, ConversationState.RECOGNIZING)
        self.controller.begin_thinking()
        self.assertEqual(self.controller.state, ConversationState.THINKING)
        self.controller.begin_speaking()
        self.assertEqual(self.controller.state, ConversationState.SPEAKING)

    def test_finish_turn_returns_to_listening_and_resets_idle_deadline(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()
        self.clock.now = 29.3
        self.controller.begin_recognition()
        self.controller.begin_thinking()
        self.controller.begin_speaking()
        self.controller.finish_turn()

        self.clock.now = 29.599
        self.assertFalse(self.controller.ready_after_playback())
        self.assertEqual(self.controller.state, ConversationState.SPEAKING)
        self.clock.now = 29.6
        self.assertTrue(self.controller.ready_after_playback())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.clock.now = 59.5
        self.assertFalse(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.clock.now = 59.6
        self.assertTrue(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_expire_if_idle_sleeps_only_at_the_thirty_second_boundary(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()

        self.clock.now = 30.2
        self.assertFalse(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.clock.now = 30.3
        self.assertTrue(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_recognition_without_input_preserves_idle_deadline(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()
        self.controller.begin_recognition()

        self.clock.now = 10.0
        self.controller.finish_recognition_without_input()

        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.clock.now = 30.299
        self.assertFalse(self.controller.expire_if_idle())
        self.clock.now = 30.3
        self.assertTrue(self.controller.expire_if_idle())

    def test_recognition_without_input_preserves_failure_count(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()
        self.assertFalse(self.controller.record_failure())
        self.controller.begin_recognition()

        self.controller.finish_recognition_without_input()

        self.assertTrue(self.controller.record_failure())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_two_consecutive_failures_return_to_sleep(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()

        self.assertFalse(self.controller.record_failure())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.assertTrue(self.controller.record_failure())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_successful_turn_resets_prior_failure_count(self) -> None:
        self.controller.wake()
        self.controller.finish_playback()
        self.clock.now = 0.3
        self.controller.ready_after_playback()
        self.assertFalse(self.controller.record_failure())
        self.controller.begin_recognition()
        self.controller.begin_thinking()
        self.controller.begin_speaking()
        self.controller.finish_turn()
        self.clock.now = 0.6
        self.controller.ready_after_playback()

        self.assertFalse(self.controller.record_failure())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)

    def test_rejects_illegal_transition(self) -> None:
        with self.assertRaises(RuntimeError):
            self.controller.begin_recognition()

        self.controller.wake()
        with self.assertRaises(RuntimeError):
            self.controller.wake()
        with self.assertRaises(RuntimeError):
            self.controller.begin_speaking()
        with self.assertRaises(RuntimeError):
            self.controller.finish_turn()


if __name__ == "__main__":
    unittest.main()

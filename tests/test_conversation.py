import unittest

from lumilamp.voice.conversation import ConversationController
from lumilamp.voice.state import ConversationState


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

    def test_wake_selects_response_and_enters_listening(self) -> None:
        self.assertEqual(self.controller.wake(), "我在，怎么啦？")
        self.assertEqual(self.controller.state, ConversationState.LISTENING)

    def test_wake_passes_all_confirmed_replies_to_chooser(self) -> None:
        chosen_from: list[tuple[str, ...]] = []
        controller = ConversationController(
            clock=self.clock,
            choose=lambda replies: chosen_from.append(replies) or replies[0],
        )

        self.assertEqual(controller.wake(), "嗯？")
        self.assertEqual(
            chosen_from,
            [("嗯？", "你好。", "我在，怎么啦？", "请吩咐。")],
        )

    def test_begin_methods_follow_the_active_turn_sequence(self) -> None:
        self.controller.wake()

        self.controller.begin_recognition()
        self.assertEqual(self.controller.state, ConversationState.RECOGNIZING)
        self.controller.begin_thinking()
        self.assertEqual(self.controller.state, ConversationState.THINKING)
        self.controller.begin_speaking()
        self.assertEqual(self.controller.state, ConversationState.SPEAKING)

    def test_finish_turn_returns_to_listening_and_resets_idle_deadline(self) -> None:
        self.controller.wake()
        self.clock.now = 29.0
        self.controller.begin_recognition()
        self.controller.begin_thinking()
        self.controller.begin_speaking()
        self.controller.finish_turn()

        self.clock.now = 58.9
        self.assertFalse(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.clock.now = 59.0
        self.assertTrue(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_expire_if_idle_sleeps_only_at_the_thirty_second_boundary(self) -> None:
        self.controller.wake()

        self.clock.now = 29.9
        self.assertFalse(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.clock.now = 30.0
        self.assertTrue(self.controller.expire_if_idle())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_two_consecutive_failures_return_to_sleep(self) -> None:
        self.controller.wake()

        self.assertFalse(self.controller.record_failure())
        self.assertEqual(self.controller.state, ConversationState.LISTENING)
        self.assertTrue(self.controller.record_failure())
        self.assertEqual(self.controller.state, ConversationState.SLEEPING)

    def test_successful_turn_resets_prior_failure_count(self) -> None:
        self.controller.wake()
        self.assertFalse(self.controller.record_failure())
        self.controller.begin_recognition()
        self.controller.begin_thinking()
        self.controller.begin_speaking()
        self.controller.finish_turn()

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

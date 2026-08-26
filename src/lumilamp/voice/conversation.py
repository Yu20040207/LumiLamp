"""Pure, deterministic state transitions for a conversation session."""

from collections.abc import Callable

from lumilamp.voice.state import ConversationState


WAKE_REPLIES = ("嗯？", "你好。", "我在，怎么啦？", "请吩咐。")


class ConversationController:
    def __init__(
        self,
        clock: Callable[[], float],
        choose: Callable[[tuple[str, ...]], str],
        timeout_seconds: float = 30.0,
    ) -> None:
        self._clock = clock
        self._choose = choose
        self._timeout_seconds = timeout_seconds
        self._deadline: float | None = None
        self._failures = 0
        self.state = ConversationState.SLEEPING

    def wake(self) -> str:
        self._require(ConversationState.SLEEPING)
        self.state = ConversationState.WAKING
        reply = self._choose(WAKE_REPLIES)
        self._failures = 0
        self._begin_listening_window()
        return reply

    def begin_recognition(self) -> None:
        self._require(ConversationState.LISTENING)
        self.state = ConversationState.RECOGNIZING

    def begin_thinking(self) -> None:
        self._require(ConversationState.RECOGNIZING)
        self.state = ConversationState.THINKING

    def begin_speaking(self) -> None:
        self._require(ConversationState.THINKING)
        self.state = ConversationState.SPEAKING

    def finish_turn(self) -> None:
        self._require(ConversationState.SPEAKING)
        self._failures = 0
        self._begin_listening_window()

    def record_failure(self) -> bool:
        if self.state is ConversationState.SLEEPING:
            raise RuntimeError("cannot record a failure while sleeping")

        self._failures += 1
        if self._failures >= 2:
            self.state = ConversationState.SLEEPING
            self._deadline = None
            return True

        self.state = ConversationState.LISTENING
        return False

    def expire_if_idle(self) -> bool:
        if self.state is not ConversationState.LISTENING:
            return False
        if self._deadline is not None and self._clock() >= self._deadline:
            self.state = ConversationState.SLEEPING
            self._deadline = None
            return True
        return False

    def _begin_listening_window(self) -> None:
        self.state = ConversationState.LISTENING
        self._deadline = self._clock() + self._timeout_seconds

    def _require(self, expected: ConversationState) -> None:
        if self.state is not expected:
            raise RuntimeError(
                f"cannot transition from {self.state.name} when {expected.name} is required"
            )

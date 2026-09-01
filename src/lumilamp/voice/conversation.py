"""Pure, deterministic state transitions for a conversation session."""

from collections.abc import Callable

from lumilamp.voice.state import ConversationState
from lumilamp.voice.wake_cache import WAKE_REPLIES


class ConversationHistory:
    """Bounded text-only user/assistant context for one voice session."""

    def __init__(self, max_turns: int = 4) -> None:
        if max_turns <= 0:
            raise ValueError("Conversation history max_turns must be positive")
        self._max_turns = max_turns
        self._messages: list[dict[str, str]] = []

    def messages(self) -> list[dict[str, str]]:
        """Return a copy so callers cannot mutate the stored session context."""
        return [message.copy() for message in self._messages]

    def append_turn(self, user_text: str, assistant_text: str) -> None:
        user = user_text.strip()
        assistant = assistant_text.strip()
        if not user or not assistant:
            raise ValueError("Conversation turns require user and assistant text")

        self._messages.extend(
            (
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            )
        )
        overflow_messages = len(self._messages) - self._max_turns * 2
        if overflow_messages > 0:
            del self._messages[:overflow_messages]

    def clear(self) -> None:
        self._messages.clear()


class ConversationController:
    def __init__(
        self,
        clock: Callable[[], float],
        choose: Callable[[tuple[str, ...]], str],
        timeout_seconds: float = 30.0,
        playback_guard_seconds: float = 0.3,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Conversation timeout must be positive")
        if playback_guard_seconds < 0:
            raise ValueError("Playback guard must not be negative")
        self._clock = clock
        self._choose = choose
        self._timeout_seconds = timeout_seconds
        self._playback_guard_seconds = playback_guard_seconds
        self._deadline: float | None = None
        self._playback_ready_at: float | None = None
        self._failures = 0
        self.state = ConversationState.SLEEPING

    def wake(self) -> str:
        self._require(ConversationState.SLEEPING)
        self.state = ConversationState.WAKING
        reply = self._choose(WAKE_REPLIES)
        self._failures = 0
        return reply

    def begin_recognition(self) -> None:
        self._require(ConversationState.LISTENING)
        self.state = ConversationState.RECOGNIZING

    def begin_thinking(self) -> None:
        self._require(ConversationState.RECOGNIZING)
        self.state = ConversationState.THINKING

    def finish_recognition_without_input(self) -> None:
        """Resume the same listening window without recording a failure."""
        self._require(ConversationState.RECOGNIZING)
        self.state = ConversationState.LISTENING

    def begin_speaking(self) -> None:
        self._require(ConversationState.THINKING)
        self.state = ConversationState.SPEAKING

    def finish_turn(self) -> None:
        self._require(ConversationState.SPEAKING)
        self._failures = 0
        self.finish_playback()

    def finish_playback(self) -> None:
        """Record the end of wake or answer playback and start the guard."""
        if self.state not in (ConversationState.WAKING, ConversationState.SPEAKING):
            raise RuntimeError("cannot finish playback outside a playback state")
        self._playback_ready_at = self._clock() + self._playback_guard_seconds

    def ready_after_playback(self) -> bool:
        """Enter listening once the injected clock has passed the playback guard."""
        if self.state not in (ConversationState.WAKING, ConversationState.SPEAKING):
            raise RuntimeError("playback guard is not active")
        if self._playback_ready_at is None or self._clock() < self._playback_ready_at:
            return False

        self._playback_ready_at = None
        self._begin_listening_window()
        return True

    def record_failure(self) -> bool:
        if self.state is ConversationState.SLEEPING:
            raise RuntimeError("cannot record a failure while sleeping")

        self._failures += 1
        if self._failures >= 2:
            self._sleep()
            return True

        self.state = ConversationState.LISTENING
        return False

    def expire_if_idle(self) -> bool:
        if self.state is not ConversationState.LISTENING:
            return False
        if self._deadline is not None and self._clock() >= self._deadline:
            self._sleep()
            return True
        return False

    def _begin_listening_window(self) -> None:
        self.state = ConversationState.LISTENING
        self._deadline = self._clock() + self._timeout_seconds

    def _sleep(self) -> None:
        self.state = ConversationState.SLEEPING
        self._deadline = None
        self._playback_ready_at = None

    def _require(self, expected: ConversationState) -> None:
        if self.state is not expected:
            raise RuntimeError(
                f"cannot transition from {self.state.name} when {expected.name} is required"
            )

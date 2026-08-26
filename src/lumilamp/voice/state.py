"""States for a wake-word conversation session."""

from enum import Enum, auto


class ConversationState(Enum):
    SLEEPING = auto()
    WAKING = auto()
    LISTENING = auto()
    RECOGNIZING = auto()
    THINKING = auto()
    SPEAKING = auto()

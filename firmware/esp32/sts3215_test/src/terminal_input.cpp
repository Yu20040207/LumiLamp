#include "terminal_input.h"

namespace {
constexpr std::size_t kMaximumLineLength = 63;

TerminalInputEvent makeEvent(TerminalInputAction action,
                             const std::string& line) {
  return {action, line};
}
}  // namespace

TerminalInputEvent TerminalInput::push(char character) {
  if (character == '\r') {
    return makeEvent(TerminalInputAction::None, line_);
  }

  if (character == '\n') {
    const TerminalInputEvent submitted =
        makeEvent(TerminalInputAction::SubmitLine, line_);
    line_.clear();
    return submitted;
  }

  if (character == '\b' || static_cast<unsigned char>(character) == 127) {
    if (line_.empty()) {
      return makeEvent(TerminalInputAction::None, line_);
    }
    line_.pop_back();
    return makeEvent(TerminalInputAction::EraseCharacter, line_);
  }

  const unsigned char byte = static_cast<unsigned char>(character);
  if (byte < 32 || byte > 126 || line_.size() >= kMaximumLineLength) {
    return makeEvent(TerminalInputAction::None, line_);
  }

  line_ += character;
  return makeEvent(TerminalInputAction::EchoCharacter, line_);
}

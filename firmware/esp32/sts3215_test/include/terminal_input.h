#pragma once

#include <string>

enum class TerminalInputAction {
  None,
  EchoCharacter,
  EraseCharacter,
  SubmitLine,
};

struct TerminalInputEvent {
  TerminalInputAction action;
  std::string line;
};

class TerminalInput {
 public:
  TerminalInputEvent push(char character);

 private:
  std::string line_;
};

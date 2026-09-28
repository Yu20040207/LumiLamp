#pragma once

#include <string>

enum class CommandType {
  Invalid,
  Help,
  Ping,
  Status,
  TorqueOn,
  TorqueOff,
  MoveRelative,
  LedTest,
};

struct Command {
  CommandType type;
  float value;
};

class CommandParser {
 public:
  static Command parse(const std::string& text);
};

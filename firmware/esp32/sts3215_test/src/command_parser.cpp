#include "command_parser.h"

#include <cerrno>
#include <cstdlib>
#include <sstream>

namespace {
Command makeCommand(CommandType type, float value = 0.0f) {
  Command command = {type, value};
  return command;
}
}  // namespace

Command CommandParser::parse(const std::string& text) {
  std::istringstream input(text);
  std::string verb;
  std::string extra;
  input >> verb;

  if (verb == "help" && !(input >> extra)) return makeCommand(CommandType::Help);
  if (verb == "ping" && !(input >> extra)) return makeCommand(CommandType::Ping);
  if (verb == "status" && !(input >> extra)) return makeCommand(CommandType::Status);
  if (verb == "ledtest" && !(input >> extra)) return makeCommand(CommandType::LedTest);

  if (verb == "torque") {
    std::string state;
    input >> state;
    if (input >> extra) return makeCommand(CommandType::Invalid);
    if (state == "on") return makeCommand(CommandType::TorqueOn);
    if (state == "off") return makeCommand(CommandType::TorqueOff);
    return makeCommand(CommandType::Invalid);
  }

  if (verb == "move") {
    std::string valueText;
    input >> valueText;
    if (valueText.empty() || (input >> extra)) {
      return makeCommand(CommandType::Invalid);
    }
    char* end = 0;
    errno = 0;
    const float value = std::strtof(valueText.c_str(), &end);
    if (errno != 0 || end == valueText.c_str() || *end != '\0') {
      return makeCommand(CommandType::Invalid);
    }
    return makeCommand(CommandType::MoveRelative, value);
  }

  return makeCommand(CommandType::Invalid);
}

#include <unity.h>

#include "command_parser.h"

void setUp() {}
void tearDown() {}

void test_parses_status() {
  const Command command = CommandParser::parse("status");
  TEST_ASSERT_EQUAL_INT(CommandType::Status, command.type);
}

void test_parses_positive_relative_move() {
  const Command command = CommandParser::parse("move 5");
  TEST_ASSERT_EQUAL_INT(CommandType::MoveRelative, command.type);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 5.0f, command.value);
}

void test_parses_negative_relative_move() {
  const Command command = CommandParser::parse("move -5");
  TEST_ASSERT_EQUAL_INT(CommandType::MoveRelative, command.type);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, -5.0f, command.value);
}

void test_rejects_extra_arguments() {
  const Command command = CommandParser::parse("status now");
  TEST_ASSERT_EQUAL_INT(CommandType::Invalid, command.type);
}

void test_rejects_non_numeric_move() {
  const Command command = CommandParser::parse("move left");
  TEST_ASSERT_EQUAL_INT(CommandType::Invalid, command.type);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_parses_status);
  RUN_TEST(test_parses_positive_relative_move);
  RUN_TEST(test_parses_negative_relative_move);
  RUN_TEST(test_rejects_extra_arguments);
  RUN_TEST(test_rejects_non_numeric_move);
  return UNITY_END();
}

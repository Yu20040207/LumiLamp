#include <unity.h>

#include "terminal_input.h"

void setUp() {}
void tearDown() {}

void test_echoes_visible_character() {
  TerminalInput input;
  const TerminalInputEvent event = input.push('p');

  TEST_ASSERT_EQUAL_INT(TerminalInputAction::EchoCharacter, event.action);
  TEST_ASSERT_EQUAL_STRING("p", event.line.c_str());
}

void test_backspace_removes_last_character() {
  TerminalInput input;
  input.push('p');
  input.push('i');
  const TerminalInputEvent event = input.push('\b');

  TEST_ASSERT_EQUAL_INT(TerminalInputAction::EraseCharacter, event.action);
  TEST_ASSERT_EQUAL_STRING("p", event.line.c_str());
}

void test_newline_submits_and_clears_line() {
  TerminalInput input;
  input.push('p');
  input.push('i');
  input.push('n');
  input.push('g');

  const TerminalInputEvent submitted = input.push('\n');
  const TerminalInputEvent next = input.push('s');

  TEST_ASSERT_EQUAL_INT(TerminalInputAction::SubmitLine, submitted.action);
  TEST_ASSERT_EQUAL_STRING("ping", submitted.line.c_str());
  TEST_ASSERT_EQUAL_INT(TerminalInputAction::EchoCharacter, next.action);
  TEST_ASSERT_EQUAL_STRING("s", next.line.c_str());
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_echoes_visible_character);
  RUN_TEST(test_backspace_removes_last_character);
  RUN_TEST(test_newline_submits_and_clears_line);
  return UNITY_END();
}

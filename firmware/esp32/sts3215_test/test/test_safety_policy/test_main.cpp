#include <unity.h>

#include "safety_policy.h"

void setUp() {}
void tearDown() {}

void test_rejects_invalid_telemetry() {
  const ServoTelemetry telemetry{false, 2048, 12.0f, 25, 0, 0};
  const SafetyDecision decision = SafetyPolicy::validateStatus(telemetry);
  TEST_ASSERT_FALSE(decision.allowed);
}

void test_rejects_temperature_at_limit() {
  const ServoTelemetry telemetry{true, 2048, 12.0f, 65, 0, 0};
  const SafetyDecision decision = SafetyPolicy::validateStatus(telemetry);
  TEST_ASSERT_FALSE(decision.allowed);
}

void test_rejects_voltage_below_safe_range() {
  const ServoTelemetry telemetry{true, 2048, 8.9f, 25, 0, 0};
  const SafetyDecision decision = SafetyPolicy::validateStatus(telemetry);
  TEST_ASSERT_FALSE(decision.allowed);
}

void test_rejects_voltage_above_safe_range() {
  const ServoTelemetry telemetry{true, 2048, 13.1f, 25, 0, 0};
  const SafetyDecision decision = SafetyPolicy::validateStatus(telemetry);
  TEST_ASSERT_FALSE(decision.allowed);
}

void test_rejects_relative_move_over_ten_degrees() {
  const ServoTelemetry telemetry{true, 2048, 12.0f, 25, 0, 0};
  const SafetyDecision decision = SafetyPolicy::relativeTarget(telemetry, 10.1f);
  TEST_ASSERT_FALSE(decision.allowed);
}

void test_converts_five_degrees_to_safe_position_steps() {
  const ServoTelemetry telemetry{true, 2048, 12.0f, 25, 0, 0};
  const SafetyDecision decision = SafetyPolicy::relativeTarget(telemetry, 5.0f);
  TEST_ASSERT_TRUE(decision.allowed);
  TEST_ASSERT_INT_WITHIN(1, 2105, decision.targetPosition);
}

void test_clamps_target_to_valid_position_range() {
  const ServoTelemetry telemetry{true, 4090, 12.0f, 25, 0, 0};
  const SafetyDecision decision = SafetyPolicy::relativeTarget(telemetry, 5.0f);
  TEST_ASSERT_TRUE(decision.allowed);
  TEST_ASSERT_EQUAL_INT(4095, decision.targetPosition);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_rejects_invalid_telemetry);
  RUN_TEST(test_rejects_temperature_at_limit);
  RUN_TEST(test_rejects_voltage_below_safe_range);
  RUN_TEST(test_rejects_voltage_above_safe_range);
  RUN_TEST(test_rejects_relative_move_over_ten_degrees);
  RUN_TEST(test_converts_five_degrees_to_safe_position_steps);
  RUN_TEST(test_clamps_target_to_valid_position_range);
  return UNITY_END();
}

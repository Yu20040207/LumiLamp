#include "safety_policy.h"

#include <cmath>

namespace {
const float kMinimumVoltage = 9.0f;
const float kMaximumVoltage = 13.0f;
const int kMaximumTemperature = 65;
const float kMaximumRelativeMoveDegrees = 10.0f;
const float kDegreesPerStep = 0.087f;
const int kMinimumPosition = 0;
const int kMaximumPosition = 4095;

SafetyDecision reject(const char* reason) {
  SafetyDecision result = {false, -1, reason};
  return result;
}
}  // namespace

SafetyDecision SafetyPolicy::validateStatus(const ServoTelemetry& telemetry) {
  if (!telemetry.valid) {
    return reject("servo telemetry unavailable");
  }
  if (telemetry.temperature >= kMaximumTemperature) {
    return reject("servo temperature at or above 65 C");
  }
  if (telemetry.voltage < kMinimumVoltage ||
      telemetry.voltage > kMaximumVoltage) {
    return reject("servo voltage outside 9-13 V test range");
  }

  SafetyDecision result = {true, telemetry.position, "ok"};
  return result;
}

SafetyDecision SafetyPolicy::relativeTarget(const ServoTelemetry& telemetry,
                                            float deltaDegrees) {
  const SafetyDecision status = validateStatus(telemetry);
  if (!status.allowed) {
    return status;
  }
  if (std::fabs(deltaDegrees) > kMaximumRelativeMoveDegrees) {
    return reject("relative move exceeds 10 degree limit");
  }

  int target = telemetry.position +
               static_cast<int>(std::lround(deltaDegrees / kDegreesPerStep));
  if (target < kMinimumPosition) {
    target = kMinimumPosition;
  } else if (target > kMaximumPosition) {
    target = kMaximumPosition;
  }

  SafetyDecision result = {true, target, "ok"};
  return result;
}

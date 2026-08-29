#pragma once

struct ServoTelemetry {
  bool valid;
  int position;
  float voltage;
  int temperature;
  int load;
  int current;
};

struct SafetyDecision {
  bool allowed;
  int targetPosition;
  const char* reason;
};

class SafetyPolicy {
 public:
  static SafetyDecision validateStatus(const ServoTelemetry& telemetry);
  static SafetyDecision relativeTarget(const ServoTelemetry& telemetry,
                                       float deltaDegrees);
};

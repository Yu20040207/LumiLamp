#include <Arduino.h>
#include <esp32-hal-rgb-led.h>
#include <Adafruit_NeoPixel.h>
#include <SCServo.h>

#include <string>

#include "command_parser.h"
#include "safety_policy.h"
#include "terminal_input.h"

namespace {
const int kServoId = 1;
const int kServoRxPin = 18;
const int kServoTxPin = 17;
const unsigned long kServoBaud = 1000000;
const unsigned int kMoveSpeed = 200;
const unsigned char kMoveAcceleration = 10;
const unsigned long kStatusLedIntervalMs = 20;
const uint8_t kStatusLedBrightness = 96;
const int kWs2812DataPin = 4;
const uint16_t kWs2812PixelCount = 20;
const uint8_t kWs2812Brightness = 32;
const unsigned long kWs2812StepIntervalMs = 120;

Adafruit_NeoPixel strip(kWs2812PixelCount, kWs2812DataPin, NEO_GRB + NEO_KHZ800);
bool ledTestActive = false;
uint16_t ledTestIndex = 0;
unsigned long lastLedTestUpdate = 0;

SMS_STS servo;
TerminalInput terminalInput;
uint16_t statusLedHue = 0;
unsigned long lastStatusLedUpdate = 0;

void writeStatusLed(uint16_t hue) {
  const uint8_t sector = hue >> 8;
  const uint8_t offset = hue & 0xff;
  const uint8_t rising = offset;
  const uint8_t falling = 255 - offset;
  uint8_t red = 0;
  uint8_t green = 0;
  uint8_t blue = 0;

  switch (sector / 43) {
    case 0:
      red = 255;
      green = rising * 6;
      break;
    case 1:
      red = falling * 6;
      green = 255;
      break;
    case 2:
      green = 255;
      blue = rising * 6;
      break;
    case 3:
      green = falling * 6;
      blue = 255;
      break;
    case 4:
      red = rising * 6;
      blue = 255;
      break;
    default:
      red = 255;
      blue = falling * 6;
      break;
  }

  neopixelWrite(RGB_BUILTIN, red * kStatusLedBrightness / 255,
                green * kStatusLedBrightness / 255,
                blue * kStatusLedBrightness / 255);
}

void updateStatusLed() {
  // The onboard RGB LED shares the RMT peripheral with the WS2811 strip.
  // Keep it static so it cannot interrupt strip.show().
}

void printPrompt() { Serial.print("> "); }

void printHelp() {
  Serial.println("Commands:");
  Serial.println("  ping        - find servo ID 1");
  Serial.println("  status      - read position/voltage/temp/load/current");
  Serial.println("  torque on   - enable servo torque");
  Serial.println("  torque off  - disable servo torque");
  Serial.println("  move DEG    - relative move, range -10.0 to +10.0 degrees");
  Serial.println("  help");
  Serial.println("  ledtest     - start/stop low-brightness WS2812 chase on GPIO4");
}

void updateLedTest() {
  // Static-color test: no periodic strip refresh, isolating power/signal issues.
}

ServoTelemetry readTelemetry() {
  servo.FeedBack(kServoId);
  if (servo.getLastError()) {
    ServoTelemetry failed = {false, 0, 0.0f, 0, 0, 0};
    return failed;
  }

  ServoTelemetry telemetry = {
      true,
      servo.ReadPos(-1),
      servo.ReadVoltage(-1) * 0.1f,
      servo.ReadTemper(-1),
      servo.ReadLoad(-1),
      servo.ReadCurrent(-1),
  };
  return telemetry;
}

void printTelemetry(const ServoTelemetry& telemetry) {
  if (!telemetry.valid) {
    Serial.println("ERROR: no valid feedback from servo ID 1");
    return;
  }
  Serial.printf("position=%d voltage=%.1fV temperature=%dC load=%d current_raw=%d\n",
                telemetry.position, telemetry.voltage, telemetry.temperature,
                telemetry.load, telemetry.current);
}

void execute(const Command& command) {
  switch (command.type) {
    case CommandType::Help:
      printHelp();
      break;
    case CommandType::Ping: {
      const int foundId = servo.Ping(kServoId);
      if (servo.getLastError()) {
        Serial.println("ERROR: servo ID 1 did not respond");
      } else {
        Serial.printf("OK: servo responded, ID=%d\n", foundId);
      }
      break;
    }
    case CommandType::Status:
      printTelemetry(readTelemetry());
      break;
    case CommandType::TorqueOn:
      servo.EnableTorque(kServoId, 1);
      Serial.println(servo.getLastError() ? "ERROR: torque on failed"
                                          : "OK: torque enabled");
      break;
    case CommandType::TorqueOff:
      servo.EnableTorque(kServoId, 0);
      Serial.println(servo.getLastError() ? "ERROR: torque off failed"
                                          : "OK: torque disabled");
      break;
    case CommandType::LedTest:
      ledTestActive = !ledTestActive;
      if (ledTestActive) {
        for (uint16_t pixel = 0; pixel < kWs2812PixelCount; ++pixel) {
          strip.setPixelColor(pixel, strip.Color(0, 0, 255));
        }
        strip.show();
        Serial.println("OK: WS2811 static blue test started on GPIO4 (20 logical pixels)");
      } else {
        strip.clear();
        strip.show();
        Serial.println("OK: WS2812 led test stopped");
      }
      break;
    case CommandType::MoveRelative: {
      const ServoTelemetry telemetry = readTelemetry();
      const SafetyDecision decision =
          SafetyPolicy::relativeTarget(telemetry, command.value);
      if (!decision.allowed) {
        Serial.printf("BLOCKED: %s\n", decision.reason);
        servo.EnableTorque(kServoId, 0);
        break;
      }
      servo.EnableTorque(kServoId, 1);
      if (servo.getLastError()) {
        Serial.println("ERROR: cannot enable torque");
        break;
      }
      servo.WritePosEx(kServoId, decision.targetPosition, kMoveSpeed,
                       kMoveAcceleration);
      if (servo.getLastError()) {
        Serial.println("ERROR: move command failed");
        servo.EnableTorque(kServoId, 0);
      } else {
        Serial.printf("OK: target=%d (relative %.2f degrees)\n",
                      decision.targetPosition, command.value);
      }
      break;
    }
    case CommandType::Invalid:
    default:
      Serial.println("ERROR: invalid command; type 'help'");
      break;
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  neopixelWrite(RGB_BUILTIN, 0, 0, kStatusLedBrightness);
  strip.begin();
  strip.setBrightness(kWs2812Brightness);
  strip.clear();
  strip.show();
  Serial2.begin(kServoBaud, SERIAL_8N1, kServoRxPin, kServoTxPin);
  servo.pSerial = &Serial2;
  delay(1000);

  Serial.println();
  Serial.println("LumiLamp STS3215 safe test console");
  Serial.println("GPIO17=TX -> URT-2 TXD, GPIO18=RX <- URT-2 RXD");
  Serial.println("No automatic movement. Type 'help'.");

  servo.EnableTorque(kServoId, 0);
  if (servo.getLastError()) {
    Serial.println("NOTICE: servo not responding yet; check power and wiring");
  } else {
    Serial.println("OK: startup torque disabled");
  }
  printPrompt();
}

void loop() {
  updateStatusLed();
  updateLedTest();
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    const TerminalInputEvent event = terminalInput.push(ch);
    if (event.action == TerminalInputAction::EchoCharacter) {
      Serial.print(ch);
    } else if (event.action == TerminalInputAction::EraseCharacter) {
      Serial.print("\b \b");
    } else if (event.action == TerminalInputAction::SubmitLine) {
      Serial.println();
      if (!event.line.empty()) {
        execute(CommandParser::parse(event.line));
      }
      printPrompt();
    }
  }
}

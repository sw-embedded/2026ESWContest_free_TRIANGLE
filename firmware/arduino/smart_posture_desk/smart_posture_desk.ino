/*
 * 스마트 자세 교정 책상 - Arduino Uno R3 모터 제어기
 *
 * 사용 하드웨어
 *   - A4988 + NEMA17 17HS3401S-T8x8: 상판 기울기
 *   - L298N + 12 V 리니어 액추에이터: 책상 높이
 *   - Active-LOW 리미트 스위치, 비상정지, 아날로그 전류 센서
 *
 * 라즈베리파이 통신: USB 시리얼, 9600 baud
 * N/W/C/H 상태 프로토콜을 사용하며 줄바꿈 없는 한 글자 명령도 지원한다.
 */

#include <Arduino.h>
#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// ----------------------------- 핀 배치 ---------------------------------

const uint8_t PIN_STEP = 2;
const uint8_t PIN_DIR = 3;
const uint8_t PIN_STEP_ENABLE = 4;   // A4988 ENABLE, LOW 활성

const uint8_t PIN_ACTUATOR_PWM = 5;  // L298N ENA, ENA 점퍼 제거
const uint8_t PIN_ACTUATOR_IN1 = 6;
const uint8_t PIN_ACTUATOR_IN2 = 7;

const uint8_t PIN_TILT_BOTTOM_LIMIT = 8;
const uint8_t PIN_TILT_TOP_LIMIT = 9;
const uint8_t PIN_HEIGHT_TOP_LIMIT = 10;
const uint8_t PIN_HEIGHT_BOTTOM_LIMIT = 11;
const uint8_t PIN_EMERGENCY_STOP = 12;
const uint8_t PIN_CURRENT_SENSOR = A0;

// 센서를 연결하지 않은 무부하 벤치 시험에서만 false로 변경한다.
const bool LIMIT_SWITCHES_ENABLED = true;
const bool EMERGENCY_STOP_ENABLED = true;
const bool CURRENT_SENSOR_ENABLED = true;

// --------------------------- 기구 설정 ---------------------------------

const float MOTOR_FULL_STEPS_PER_REV = 200.0f;
const float MICROSTEPS = 8.0f;              // MS1=HIGH, MS2=HIGH, MS3=LOW
const float LEAD_SCREW_MM_PER_REV = 8.0f;   // T8x8
const float TILT_STEPS_PER_MM =
    (MOTOR_FULL_STEPS_PER_REV * MICROSTEPS) / LEAD_SCREW_MM_PER_REV;

// 실제 기구가 반대로 움직이면 HIGH를 LOW로 변경한다.
const uint8_t TILT_UP_DIR_LEVEL = HIGH;

// 실제 기구에서 보수적으로 실측·보정해야 하는 값이다.
const float TILT_MAX_TRAVEL_MM = 100.0f;
const float TILT_SPEED_MM_PER_SEC = 4.0f;
const float AUTO_TILT_TARGET_MM = 5.0f;

// 100 mm / 9.5 mm/s의 이론값을 올림한 최대 구동 시간이다.
const unsigned long ACTUATOR_MAX_RUN_MS = 10527UL;
const uint8_t ACTUATOR_RUN_PWM = 180;
const uint8_t ACTUATOR_REVERSE_PWM = 100;
const unsigned long ACTUATOR_PWM_RAMP_INTERVAL_MS = 20UL;
const uint8_t ACTUATOR_PWM_RAMP_STEP = 5;

// 무부하/정상 하중/구속 상태를 측정한 뒤 실제 센서에 맞게 보정한다.
const int CURRENT_THRESHOLD = 500;
const uint8_t OVERCURRENT_SAMPLE_COUNT = 3;
const unsigned long CURRENT_SAMPLE_INTERVAL_MS = 10UL;
const unsigned long SAFETY_REVERSE_PAUSE_MS = 100UL;
const unsigned long SAFETY_REVERSE_MS = 300UL;

const unsigned long COMMAND_WATCHDOG_MS = 3000UL;
const unsigned long TILT_MOTION_TIMEOUT_MS = 30000UL;
const unsigned long SERIAL_IDLE_COMMAND_MS = 30UL;
const uint8_t STEP_PULSE_US = 3;

// ----------------------------- 동작 상태 --------------------------------

enum TiltMode {
  TILT_IDLE,
  TILT_MOVING,
  TILT_HOMING
};

enum HeightMode {
  HEIGHT_STOPPED,
  HEIGHT_UP,
  HEIGHT_DOWN,
  HEIGHT_BRAKING,
  HEIGHT_SAFETY_PAUSE,
  HEIGHT_SAFETY_REVERSING
};

TiltMode tiltMode = TILT_IDLE;
HeightMode heightMode = HEIGHT_STOPPED;
HeightMode heightTravelDirection = HEIGHT_STOPPED;

long tiltPositionSteps = 0;
long tiltTargetSteps = 0;
bool tiltZeroSet = false;

unsigned long tiltStepIntervalUs = 0;
unsigned long lastTiltStepUs = 0;
unsigned long tiltMotionStartedMs = 0;

unsigned long heightMotionStartedMs = 0;
unsigned long heightRequestedRunMs = 0;
unsigned long lastHeightPwmUpdateMs = 0;
unsigned long lastCurrentSampleMs = 0;
uint8_t currentHeightPwm = 0;
uint8_t targetHeightPwm = 0;
uint8_t overcurrentSamples = 0;
const __FlashStringHelper *heightBrakeReason = NULL;

unsigned long lastValidCommandMs = 0;

const size_t COMMAND_BUFFER_SIZE = 64;
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;
bool discardingLongCommand = false;
unsigned long lastSerialByteMs = 0;

// --------------------------- 공통 안전 함수 ------------------------------

bool inputActive(uint8_t pin) {
  return digitalRead(pin) == LOW;
}

bool tiltBottomLimitActive() {
  return LIMIT_SWITCHES_ENABLED && inputActive(PIN_TILT_BOTTOM_LIMIT);
}

bool tiltTopLimitActive() {
  return LIMIT_SWITCHES_ENABLED && inputActive(PIN_TILT_TOP_LIMIT);
}

bool heightTopLimitActive() {
  return LIMIT_SWITCHES_ENABLED && inputActive(PIN_HEIGHT_TOP_LIMIT);
}

bool heightBottomLimitActive() {
  return LIMIT_SWITCHES_ENABLED && inputActive(PIN_HEIGHT_BOTTOM_LIMIT);
}

bool emergencyStopActive() {
  return EMERGENCY_STOP_ENABLED && inputActive(PIN_EMERGENCY_STOP);
}

bool limitConflictActive() {
  return LIMIT_SWITCHES_ENABLED &&
         ((tiltBottomLimitActive() && tiltTopLimitActive()) ||
          (heightBottomLimitActive() && heightTopLimitActive()));
}

bool anyMotionActive() {
  return tiltMode != TILT_IDLE || heightMode != HEIGHT_STOPPED;
}

long mmToSteps(float millimeters) {
  return lround(millimeters * TILT_STEPS_PER_MM);
}

float stepsToMm(long steps) {
  return ((float)steps) / TILT_STEPS_PER_MM;
}

unsigned long speedToStepIntervalUs(float millimetersPerSecond) {
  const float stepsPerSecond = millimetersPerSecond * TILT_STEPS_PER_MM;
  return (unsigned long)(1000000.0f / stepsPerSecond);
}

void enableStepper(bool enabled) {
  digitalWrite(PIN_STEP_ENABLE, enabled ? LOW : HIGH);
}

void stopTilt(const __FlashStringHelper *reason) {
  const bool wasMoving = tiltMode != TILT_IDLE;
  tiltMode = TILT_IDLE;
  digitalWrite(PIN_STEP, LOW);
  enableStepper(false);

  if (wasMoving) {
    Serial.print(F("TILT_STOP "));
    Serial.println(reason);
  }
}

void stopHeightNow(const __FlashStringHelper *reason) {
  const bool wasMoving = heightMode != HEIGHT_STOPPED;
  analogWrite(PIN_ACTUATOR_PWM, 0);
  digitalWrite(PIN_ACTUATOR_IN1, LOW);
  digitalWrite(PIN_ACTUATOR_IN2, LOW);
  heightMode = HEIGHT_STOPPED;
  heightTravelDirection = HEIGHT_STOPPED;
  currentHeightPwm = 0;
  targetHeightPwm = 0;
  heightBrakeReason = NULL;
  overcurrentSamples = 0;

  if (wasMoving) {
    Serial.print(F("HEIGHT_STOP "));
    Serial.println(reason);
  }
}

void stopAll(const __FlashStringHelper *reason) {
  stopTilt(reason);
  stopHeightNow(reason);
}

void printStatus() {
  Serial.print(F("STATUS TILT_ZERO_SET="));
  Serial.print(tiltZeroSet ? 1 : 0);
  Serial.print(F(" TILT_MM="));
  Serial.print(stepsToMm(tiltPositionSteps), 2);
  Serial.print(F(" TILT_MODE="));
  Serial.print((int)tiltMode);
  Serial.print(F(" HEIGHT_MODE="));
  Serial.print((int)heightMode);
  Serial.print(F(" CURRENT="));
  Serial.print(analogRead(PIN_CURRENT_SENSOR));
  Serial.print(F(" LIMITS="));
  Serial.print(tiltBottomLimitActive() ? 1 : 0);
  Serial.print(tiltTopLimitActive() ? 1 : 0);
  Serial.print(heightBottomLimitActive() ? 1 : 0);
  Serial.print(heightTopLimitActive() ? 1 : 0);
  Serial.print(F(" ESTOP="));
  Serial.println(emergencyStopActive() ? 1 : 0);
}

// -------------------------- 기울기 제어 ---------------------------------

void setTiltZero() {
  if (anyMotionActive()) {
    Serial.println(F("ERR BUSY"));
    return;
  }

  tiltPositionSteps = 0;
  tiltTargetSteps = 0;
  tiltZeroSet = true;
  Serial.println(F("OK SET_ZERO"));
}

void startTiltHome() {
  if (tiltMode != TILT_IDLE) {
    Serial.println(F("ERR BUSY_TILT"));
    return;
  }
  if (heightMode != HEIGHT_STOPPED) {
    Serial.println(F("ERR BUSY_HEIGHT"));
    return;
  }
  if (emergencyStopActive()) {
    Serial.println(F("ERR EMERGENCY_ACTIVE"));
    return;
  }
  if (!LIMIT_SWITCHES_ENABLED) {
    Serial.println(F("ERR HOME_LIMITS_DISABLED"));
    return;
  }
  if (limitConflictActive()) {
    Serial.println(F("ERR LIMIT_CONFLICT"));
    return;
  }
  if (tiltBottomLimitActive()) {
    tiltPositionSteps = 0;
    tiltTargetSteps = 0;
    tiltZeroSet = true;
    Serial.println(F("DONE HOME"));
    return;
  }

  digitalWrite(PIN_DIR, TILT_UP_DIR_LEVEL == HIGH ? LOW : HIGH);
  tiltMode = TILT_HOMING;
  tiltStepIntervalUs = speedToStepIntervalUs(TILT_SPEED_MM_PER_SEC);
  tiltMotionStartedMs = millis();
  lastTiltStepUs = micros();
  enableStepper(true);
  Serial.println(F("OK HOME"));
}

void startTiltMoveMm(float targetMm,
                     const __FlashStringHelper *acceptedCommand) {
  if (!tiltZeroSet) {
    Serial.println(F("ERR TILT_ZERO_NOT_SET"));
    return;
  }
  if (tiltMode != TILT_IDLE) {
    Serial.println(F("ERR BUSY_TILT"));
    return;
  }
  if (heightMode != HEIGHT_STOPPED) {
    Serial.println(F("ERR BUSY_HEIGHT"));
    return;
  }
  if (emergencyStopActive()) {
    Serial.println(F("ERR EMERGENCY_ACTIVE"));
    return;
  }
  if (limitConflictActive()) {
    Serial.println(F("ERR LIMIT_CONFLICT"));
    return;
  }
  if (!isfinite(targetMm) || targetMm < 0.0f ||
      targetMm > TILT_MAX_TRAVEL_MM) {
    Serial.println(F("ERR TILT_RANGE"));
    return;
  }

  tiltTargetSteps = mmToSteps(targetMm);
  if (tiltTargetSteps == tiltPositionSteps) {
    Serial.print(F("DONE "));
    Serial.println(acceptedCommand);
    return;
  }

  const bool movingUp = tiltTargetSteps > tiltPositionSteps;
  if ((movingUp && tiltTopLimitActive()) ||
      (!movingUp && tiltBottomLimitActive())) {
    Serial.println(F("ERR TILT_LIMIT_ACTIVE"));
    return;
  }

  const uint8_t directionLevel =
      movingUp ? TILT_UP_DIR_LEVEL : (TILT_UP_DIR_LEVEL == HIGH ? LOW : HIGH);
  digitalWrite(PIN_DIR, directionLevel);

  tiltMode = TILT_MOVING;
  tiltStepIntervalUs = speedToStepIntervalUs(TILT_SPEED_MM_PER_SEC);
  tiltMotionStartedMs = millis();
  lastTiltStepUs = micros();
  enableStepper(true);
  Serial.print(F("OK "));
  Serial.println(acceptedCommand);
}

void updateTilt() {
  if (tiltMode == TILT_IDLE) {
    return;
  }

  if (millis() - tiltMotionStartedMs > TILT_MOTION_TIMEOUT_MS) {
    stopTilt(F("TIMEOUT"));
    Serial.println(F("ERR TILT_TIMEOUT"));
    return;
  }

  const bool homing = tiltMode == TILT_HOMING;
  const bool movingUp = !homing && tiltTargetSteps > tiltPositionSteps;

  if (!movingUp && tiltBottomLimitActive()) {
    const bool expectedBottom = homing || tiltTargetSteps == 0;
    tiltPositionSteps = 0;
    tiltTargetSteps = 0;
    tiltZeroSet = true;
    stopTilt(F("BOTTOM_LIMIT"));
    if (homing) {
      Serial.println(F("DONE HOME"));
    } else if (expectedBottom) {
      Serial.println(F("DONE TILT"));
    } else {
      Serial.println(F("ERR TILT_BOTTOM_LIMIT"));
    }
    return;
  }

  if (movingUp && tiltTopLimitActive()) {
    tiltPositionSteps = mmToSteps(TILT_MAX_TRAVEL_MM);
    tiltTargetSteps = tiltPositionSteps;
    stopTilt(F("TOP_LIMIT"));
    Serial.println(F("ERR TILT_TOP_LIMIT"));
    return;
  }

  const unsigned long nowUs = micros();
  if ((unsigned long)(nowUs - lastTiltStepUs) < tiltStepIntervalUs) {
    return;
  }
  lastTiltStepUs = nowUs;

  digitalWrite(PIN_STEP, HIGH);
  delayMicroseconds(STEP_PULSE_US);
  digitalWrite(PIN_STEP, LOW);

  if (!homing) {
    tiltPositionSteps += movingUp ? 1 : -1;
    if (tiltPositionSteps == tiltTargetSteps) {
      stopTilt(F("TARGET"));
      Serial.println(F("DONE TILT"));
    }
  }
}

// ---------------------------- 높이 제어 ---------------------------------

void setHeightDirection(HeightMode direction) {
  if (direction == HEIGHT_UP) {
    digitalWrite(PIN_ACTUATOR_IN1, HIGH);
    digitalWrite(PIN_ACTUATOR_IN2, LOW);
  } else {
    digitalWrite(PIN_ACTUATOR_IN1, LOW);
    digitalWrite(PIN_ACTUATOR_IN2, HIGH);
  }
}

void startHeight(HeightMode direction, unsigned long requestedMs) {
  if (tiltMode != TILT_IDLE) {
    Serial.println(F("ERR BUSY_TILT"));
    return;
  }
  if (heightMode != HEIGHT_STOPPED) {
    Serial.println(F("ERR BUSY_HEIGHT"));
    return;
  }
  if (emergencyStopActive()) {
    Serial.println(F("ERR EMERGENCY_ACTIVE"));
    return;
  }
  if (limitConflictActive()) {
    Serial.println(F("ERR LIMIT_CONFLICT"));
    return;
  }
  if (requestedMs == 0 || requestedMs > ACTUATOR_MAX_RUN_MS) {
    Serial.println(F("ERR HEIGHT_TIME_RANGE"));
    return;
  }
  if ((direction == HEIGHT_UP && heightTopLimitActive()) ||
      (direction == HEIGHT_DOWN && heightBottomLimitActive())) {
    Serial.println(F("ERR HEIGHT_LIMIT_ACTIVE"));
    return;
  }

  setHeightDirection(direction);
  heightMode = direction;
  heightTravelDirection = direction;
  heightRequestedRunMs = requestedMs;
  heightMotionStartedMs = millis();
  lastHeightPwmUpdateMs = millis();
  lastCurrentSampleMs = millis();
  currentHeightPwm = 0;
  targetHeightPwm = ACTUATOR_RUN_PWM;
  overcurrentSamples = 0;
  analogWrite(PIN_ACTUATOR_PWM, 0);
  Serial.println(F("OK HEIGHT"));
}

void beginHeightSoftStop(const __FlashStringHelper *reason) {
  if (heightMode == HEIGHT_STOPPED || heightMode == HEIGHT_BRAKING) {
    return;
  }
  heightMode = HEIGHT_BRAKING;
  targetHeightPwm = 0;
  heightBrakeReason = reason;
}

void startSafetyReversePause() {
  if (emergencyStopActive() || heightBottomLimitActive()) {
    return;
  }
  heightMode = HEIGHT_SAFETY_PAUSE;
  heightTravelDirection = HEIGHT_STOPPED;
  heightMotionStartedMs = millis();
  Serial.println(F("INFO SAFETY_REVERSE_PAUSE"));
}

void startSafetyReverse() {
  setHeightDirection(HEIGHT_DOWN);
  heightMode = HEIGHT_SAFETY_REVERSING;
  heightTravelDirection = HEIGHT_DOWN;
  heightMotionStartedMs = millis();
  currentHeightPwm = ACTUATOR_REVERSE_PWM;
  targetHeightPwm = ACTUATOR_REVERSE_PWM;
  analogWrite(PIN_ACTUATOR_PWM, currentHeightPwm);
  Serial.println(F("OK SAFETY_REVERSE"));
}

void updateHeightPwm() {
  if (heightMode == HEIGHT_STOPPED ||
      heightMode == HEIGHT_SAFETY_PAUSE ||
      heightMode == HEIGHT_SAFETY_REVERSING) {
    return;
  }

  const unsigned long nowMs = millis();
  if (nowMs - lastHeightPwmUpdateMs < ACTUATOR_PWM_RAMP_INTERVAL_MS) {
    return;
  }
  lastHeightPwmUpdateMs = nowMs;

  if (currentHeightPwm < targetHeightPwm) {
    const uint16_t nextPwm = currentHeightPwm + ACTUATOR_PWM_RAMP_STEP;
    currentHeightPwm =
        nextPwm > targetHeightPwm ? targetHeightPwm : (uint8_t)nextPwm;
  } else if (currentHeightPwm > targetHeightPwm) {
    currentHeightPwm =
        currentHeightPwm > ACTUATOR_PWM_RAMP_STEP
            ? currentHeightPwm - ACTUATOR_PWM_RAMP_STEP
            : 0;
  }
  analogWrite(PIN_ACTUATOR_PWM, currentHeightPwm);

  if (heightMode == HEIGHT_BRAKING && currentHeightPwm == 0) {
    const __FlashStringHelper *reason = heightBrakeReason;
    stopHeightNow(reason == NULL ? F("BRAKE") : reason);
    Serial.println(F("DONE HEIGHT"));
  }
}

void updateHeight() {
  if (heightMode == HEIGHT_STOPPED) {
    return;
  }

  if ((heightTravelDirection == HEIGHT_UP && heightTopLimitActive()) ||
      (heightTravelDirection == HEIGHT_DOWN && heightBottomLimitActive())) {
    stopHeightNow(F("LIMIT"));
    Serial.println(F("ERR HEIGHT_LIMIT"));
    return;
  }

  if ((heightMode == HEIGHT_UP || heightMode == HEIGHT_DOWN ||
       heightMode == HEIGHT_BRAKING) &&
      CURRENT_SENSOR_ENABLED &&
      millis() - lastCurrentSampleMs >= CURRENT_SAMPLE_INTERVAL_MS) {
    lastCurrentSampleMs = millis();
    if (analogRead(PIN_CURRENT_SENSOR) > CURRENT_THRESHOLD) {
      if (overcurrentSamples < OVERCURRENT_SAMPLE_COUNT) {
        ++overcurrentSamples;
      }
    } else {
      overcurrentSamples = 0;
    }

    if (overcurrentSamples >= OVERCURRENT_SAMPLE_COUNT) {
      const bool wasMovingUp = heightTravelDirection == HEIGHT_UP;
      stopHeightNow(F("OVERCURRENT"));
      Serial.println(F("ERR OVERCURRENT"));
      if (wasMovingUp) {
        startSafetyReversePause();
      }
      return;
    }
  }

  if ((heightMode == HEIGHT_UP || heightMode == HEIGHT_DOWN) &&
      millis() - heightMotionStartedMs >= heightRequestedRunMs) {
    beginHeightSoftStop(F("TIME"));
  } else if (heightMode == HEIGHT_SAFETY_PAUSE &&
             millis() - heightMotionStartedMs >= SAFETY_REVERSE_PAUSE_MS) {
    if (emergencyStopActive() || heightBottomLimitActive()) {
      stopHeightNow(F("SAFETY_REVERSE_CANCELLED"));
    } else {
      startSafetyReverse();
    }
    return;
  } else if (heightMode == HEIGHT_SAFETY_REVERSING &&
             millis() - heightMotionStartedMs >= SAFETY_REVERSE_MS) {
    stopHeightNow(F("SAFETY_REVERSE"));
    Serial.println(F("DONE SAFETY_REVERSE"));
    return;
  }

  updateHeightPwm();
}

// ------------------------- 시리얼 통신 처리 ------------------------------

void uppercase(char *text) {
  while (*text != '\0') {
    *text = (char)toupper((unsigned char)*text);
    ++text;
  }
}

bool parseFloatArgument(char *value, float &result) {
  if (value == NULL) {
    return false;
  }
  char *end = NULL;
  result = (float)strtod(value, &end);
  return end != value && *end == '\0' && isfinite(result);
}

void markValidCommand() {
  lastValidCommandMs = millis();
}

void handleCommand(char *line) {
  char *command = strtok(line, " \t");
  if (command == NULL) {
    return;
  }
  uppercase(command);

  // N=Normal, W=Warning, C=Critical, H=Heartbeat.
  if (strcmp(command, "C") == 0) {
    markValidCommand();
    startTiltMoveMm(AUTO_TILT_TARGET_MM, F("C"));
    return;
  }

  if (strcmp(command, "N") == 0) {
    markValidCommand();
    stopAll(F("COMMAND"));
    Serial.println(F("OK N"));
    return;
  }

  // WARNING 단계에서는 모터를 구동하지 않고 기존 동작도 정지한다.
  if (strcmp(command, "W") == 0) {
    markValidCommand();
    stopAll(F("COMMAND"));
    Serial.println(F("OK W"));
    return;
  }

  if (strcmp(command, "H") == 0) {
    markValidCommand();
    Serial.println(F("PONG"));
    return;
  }

  if (strcmp(command, "STOP") == 0) {
    markValidCommand();
    stopAll(F("COMMAND"));
    Serial.println(F("OK STOP"));
    return;
  }

  if (strcmp(command, "PING") == 0 || strcmp(command, "KEEPALIVE") == 0) {
    markValidCommand();
    Serial.println(F("PONG"));
    return;
  }

  if (strcmp(command, "STATUS") == 0) {
    markValidCommand();
    printStatus();
    return;
  }

  if (strcmp(command, "SET_ZERO") == 0) {
    markValidCommand();
    setTiltZero();
    return;
  }

  if (strcmp(command, "HOME") == 0) {
    markValidCommand();
    startTiltHome();
    return;
  }

  if (strcmp(command, "TILT") == 0) {
    char *value = strtok(NULL, " \t");
    float targetMm = 0.0f;
    if (!parseFloatArgument(value, targetMm) || strtok(NULL, " \t") != NULL) {
      Serial.println(F("ERR TILT_ARGUMENT"));
      return;
    }
    markValidCommand();
    startTiltMoveMm(targetMm, F("TILT"));
    return;
  }

  if (strcmp(command, "TILT_REL") == 0) {
    char *value = strtok(NULL, " \t");
    float deltaMm = 0.0f;
    if (!parseFloatArgument(value, deltaMm) ||
        strtok(NULL, " \t") != NULL) {
      Serial.println(F("ERR TILT_REL_ARGUMENT"));
      return;
    }
    if (!tiltZeroSet) {
      Serial.println(F("ERR TILT_ZERO_NOT_SET"));
      return;
    }
    markValidCommand();
    startTiltMoveMm(stepsToMm(tiltPositionSteps) + deltaMm, F("TILT_REL"));
    return;
  }

  if (strcmp(command, "HEIGHT") == 0) {
    char *direction = strtok(NULL, " \t");
    char *duration = strtok(NULL, " \t");
    if (direction == NULL || duration == NULL || strtok(NULL, " \t") != NULL) {
      Serial.println(F("ERR HEIGHT_ARGUMENT"));
      return;
    }
    uppercase(direction);
    char *end = NULL;
    const unsigned long durationMs = strtoul(duration, &end, 10);
    if (end == duration || *end != '\0') {
      Serial.println(F("ERR HEIGHT_ARGUMENT"));
      return;
    }
    if (strcmp(direction, "UP") == 0) {
      markValidCommand();
      startHeight(HEIGHT_UP, durationMs);
    } else if (strcmp(direction, "DOWN") == 0) {
      markValidCommand();
      startHeight(HEIGHT_DOWN, durationMs);
    } else {
      Serial.println(F("ERR HEIGHT_DIRECTION"));
    }
    return;
  }

  Serial.println(F("ERR UNKNOWN_COMMAND"));
}

void finishBufferedCommand() {
  if (discardingLongCommand) {
    discardingLongCommand = false;
    commandLength = 0;
    return;
  }
  commandBuffer[commandLength] = '\0';
  handleCommand(commandBuffer);
  commandLength = 0;
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    const char incoming = (char)Serial.read();
    lastSerialByteMs = millis();

    if (incoming == '\r') {
      continue;
    }
    if (incoming == '\n') {
      finishBufferedCommand();
      continue;
    }
    if (discardingLongCommand) {
      continue;
    }
    if (commandLength < COMMAND_BUFFER_SIZE - 1) {
      commandBuffer[commandLength++] = incoming;
    } else {
      commandLength = 0;
      discardingLongCommand = true;
      Serial.println(F("ERR COMMAND_TOO_LONG"));
    }
  }

  // 줄바꿈 없이 한 글자만 보내는 이전 UI와의 호환 처리다.
  if ((commandLength > 0 || discardingLongCommand) &&
      millis() - lastSerialByteMs >= SERIAL_IDLE_COMMAND_MS) {
    finishBufferedCommand();
  }
}

// ---------------------- 아두이노 시작 및 반복 실행 -------------------------

void setup() {
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR, OUTPUT);
  pinMode(PIN_STEP_ENABLE, OUTPUT);
  pinMode(PIN_ACTUATOR_PWM, OUTPUT);
  pinMode(PIN_ACTUATOR_IN1, OUTPUT);
  pinMode(PIN_ACTUATOR_IN2, OUTPUT);

  pinMode(PIN_TILT_BOTTOM_LIMIT, INPUT_PULLUP);
  pinMode(PIN_TILT_TOP_LIMIT, INPUT_PULLUP);
  pinMode(PIN_HEIGHT_TOP_LIMIT, INPUT_PULLUP);
  pinMode(PIN_HEIGHT_BOTTOM_LIMIT, INPUT_PULLUP);
  pinMode(PIN_EMERGENCY_STOP, INPUT_PULLUP);

  digitalWrite(PIN_STEP, LOW);
  enableStepper(false);
  stopHeightNow(F("BOOT"));

  Serial.begin(9600);
  lastValidCommandMs = millis();

  if (tiltBottomLimitActive() && !tiltTopLimitActive()) {
    tiltZeroSet = true;
    tiltPositionSteps = 0;
    tiltTargetSteps = 0;
  }

  Serial.println(F("READY SMART_POSTURE_DESK_V4_NWCH"));
  if (limitConflictActive()) {
    Serial.println(F("ERR LIMIT_CONFLICT"));
  }
  Serial.println(tiltZeroSet ? F("INFO TILT_ZERO_FROM_LIMIT")
                             : F("INFO SEND_HOME_OR_SET_ZERO"));
}

void loop() {
  readSerialCommands();

  if (limitConflictActive() && anyMotionActive()) {
    stopAll(F("LIMIT_CONFLICT"));
    Serial.println(F("ERR LIMIT_CONFLICT"));
  } else if (emergencyStopActive() && anyMotionActive()) {
    stopAll(F("EMERGENCY"));
    Serial.println(F("ERR EMERGENCY_STOP"));
  }

  if (anyMotionActive() &&
      millis() - lastValidCommandMs > COMMAND_WATCHDOG_MS) {
    stopAll(F("WATCHDOG"));
    Serial.println(F("ERR WATCHDOG"));
  }

  updateTilt();
  updateHeight();
}

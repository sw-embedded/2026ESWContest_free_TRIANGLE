/*
 * 스마트 자세 교정 데스크 시스템 - Arduino Uno R3 모터 제어기
 *
 * 사용 하드웨어
 *   - A4988 + NEMA17 17HS3401S-T8x8: 상판 기울기
 *   - L298N + 12 V 리니어 액추에이터: 책상 높이
 *   - D12 Active-LOW 비상정지 스위치, 아날로그 전류 센서
 *
 * 라즈베리파이 통신: USB 시리얼, 9600 baud
 * N/W/C <posture>/H/R 프로토콜을 사용한다.
 */

#include <Arduino.h>
#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// ----------------------------- 핀 배치 ---------------------------------

const uint8_t PIN_DIR = 2;
const uint8_t PIN_STEP = 3;

// A4988 ENABLE은 LOW 고정, L298N ENA는 점퍼 연결을 가정한다.
const uint8_t PIN_ACTUATOR_IN1 = 7;
const uint8_t PIN_ACTUATOR_IN2 = 8;

const uint8_t PIN_EMERGENCY_STOP = 12;
const uint8_t PIN_CURRENT_SENSOR = A0;

// 모든 안전 스위치는 INPUT_PULLUP을 사용하는 Active-LOW 배선이다.
const bool EMERGENCY_STOP_ENABLED = true;
const bool CURRENT_SENSOR_ENABLED = true;

// --------------------------- 기구 설정 ---------------------------------

const float MOTOR_FULL_STEPS_PER_REV = 200.0f;
const float MICROSTEPS = 1.0f;              // MS1/MS2/MS3 미연결: Full-Step
const float LEAD_SCREW_MM_PER_REV = 8.0f;   // T8x8
const float TILT_STEPS_PER_MM =
    (MOTOR_FULL_STEPS_PER_REV * MICROSTEPS) / LEAD_SCREW_MM_PER_REV;

// 실제 설치 방향에 따라 HIGH/LOW를 조정한다.
const uint8_t TILT_UP_DIR_LEVEL = HIGH;

// 실제 기구에서 보수적으로 실측·보정해야 하는 값이다.
const float TILT_MAX_TRAVEL_MM = 100.0f;
const float TILT_SPEED_MM_PER_SEC = 4.0f;
const float AUTO_TILT_DELTA_MM = 40.0f;
const unsigned long AUTO_TILT_UP_MS = 10000UL;
const unsigned long AUTO_TILT_DOWN_MS = 6000UL;
const unsigned long AUTO_HEIGHT_UP_MS = 4000UL;
const unsigned long AUTO_HEIGHT_DOWN_MS = 4000UL;

// 100 mm / 9.5 mm/s의 이론값을 올림한 최대 구동 시간이다.
const unsigned long ACTUATOR_MAX_RUN_MS = 10527UL;

// 무부하/정상 하중/구속 상태를 측정한 뒤 실제 센서에 맞게 보정한다.
const int CURRENT_THRESHOLD = 500;
const uint8_t OVERCURRENT_SAMPLE_COUNT = 3;
const unsigned long CURRENT_SAMPLE_INTERVAL_MS = 10UL;
const unsigned long SAFETY_REVERSE_PAUSE_MS = 100UL;
const unsigned long SAFETY_REVERSE_MS = 300UL;

const unsigned long COMMAND_WATCHDOG_MS = 3UL * 1000UL;
const unsigned long TILT_MOTION_TIMEOUT_MS = 30000UL;
const unsigned long TILT_START_DELAY_MS = 4000UL;
const unsigned long SERIAL_IDLE_COMMAND_MS = 30UL;
const uint8_t STEP_PULSE_US = 3;

// ----------------------------- 동작 상태 --------------------------------

enum TiltMode {
  TILT_IDLE,
  TILT_MOVING,
  TILT_WAITING
};

enum HeightMode {
  HEIGHT_STOPPED = 0,
  HEIGHT_UP = 1,
  HEIGHT_DOWN = 2,
  HEIGHT_SAFETY_PAUSE = 4,
  HEIGHT_SAFETY_REVERSING = 5
};

enum CorrectionType {
  CORRECTION_NONE,
  CORRECTION_TURTLE_NECK,
  CORRECTION_BENT_BACK
};

enum CorrectionPhase {
  CORRECTION_IDLE,
  CORRECTION_APPLYING,
  CORRECTION_APPLIED,
  CORRECTION_RESTORING,
  CORRECTION_FAULT
};

TiltMode tiltMode = TILT_IDLE;
HeightMode heightMode = HEIGHT_STOPPED;
HeightMode heightTravelDirection = HEIGHT_STOPPED;
CorrectionType correctionType = CORRECTION_NONE;
CorrectionPhase correctionPhase = CORRECTION_IDLE;

long tiltPositionSteps = 0;
long tiltTargetSteps = 0;
bool tiltZeroSet = false;
long correctionStartTiltSteps = 0;

unsigned long tiltStepIntervalUs = 0;
unsigned long lastTiltStepUs = 0;
unsigned long tiltMotionStartedMs = 0;

unsigned long heightMotionStartedMs = 0;
unsigned long heightRequestedRunMs = 0;
unsigned long lastCurrentSampleMs = 0;
uint8_t overcurrentSamples = 0;

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

bool emergencyStopActive() {
  return EMERGENCY_STOP_ENABLED && inputActive(PIN_EMERGENCY_STOP);
}

bool anyMotionActive() {
  return tiltMode != TILT_IDLE || heightMode != HEIGHT_STOPPED;
}

bool tiltAtHeightSafeReference() {
  return tiltZeroSet && tiltPositionSteps == 0 && tiltTargetSteps == 0;
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

unsigned long durationToStepIntervalUs(long steps,
                                       unsigned long durationMs) {
  return (durationMs * 1000UL) / (unsigned long)labs(steps);
}

void printCorrectionType(CorrectionType type) {
  if (type == CORRECTION_TURTLE_NECK) {
    Serial.print(F("TURTLE_NECK"));
  } else if (type == CORRECTION_BENT_BACK) {
    Serial.print(F("BENT_BACK"));
  } else {
    Serial.print(F("NONE"));
  }
}

void printCorrectionPhase(CorrectionPhase phase) {
  if (phase == CORRECTION_APPLYING) {
    Serial.print(F("APPLYING"));
  } else if (phase == CORRECTION_APPLIED) {
    Serial.print(F("APPLIED"));
  } else if (phase == CORRECTION_RESTORING) {
    Serial.print(F("RESTORING"));
  } else if (phase == CORRECTION_FAULT) {
    Serial.print(F("FAULT"));
  } else {
    Serial.print(F("IDLE"));
  }
}

void markCorrectionFault(const __FlashStringHelper *reason) {
  if (correctionPhase != CORRECTION_APPLYING &&
      correctionPhase != CORRECTION_RESTORING) {
    return;
  }

  correctionPhase = CORRECTION_FAULT;
  Serial.print(F("ERR CORRECTION_FAULT "));
  Serial.println(reason);
}

void finishCorrectionMotion() {
  if (correctionPhase == CORRECTION_APPLYING) {
    correctionPhase = CORRECTION_APPLIED;
    Serial.print(F("DONE CORRECTION "));
    printCorrectionType(correctionType);
    Serial.println();
  } else if (correctionPhase == CORRECTION_RESTORING) {
    correctionPhase = CORRECTION_IDLE;
    correctionType = CORRECTION_NONE;
    correctionStartTiltSteps = 0;
    Serial.println(F("DONE RESTORE"));
  }
}

void stopTilt(const __FlashStringHelper *reason) {
  const bool wasMoving = tiltMode != TILT_IDLE;
  tiltMode = TILT_IDLE;
  digitalWrite(PIN_STEP, LOW);

  if (wasMoving) {
    Serial.print(F("TILT_STOP "));
    Serial.println(reason);
  }
}

void stopHeightNow(const __FlashStringHelper *reason) {
  const bool wasMoving = heightMode != HEIGHT_STOPPED;
  digitalWrite(PIN_ACTUATOR_IN1, LOW);
  digitalWrite(PIN_ACTUATOR_IN2, LOW);
  heightMode = HEIGHT_STOPPED;
  heightTravelDirection = HEIGHT_STOPPED;
  overcurrentSamples = 0;

  if (wasMoving) {
    Serial.print(F("HEIGHT_STOP "));
    Serial.println(reason);
  }
}

void stopAll(const __FlashStringHelper *reason) {
  const bool interruptedCorrection =
      anyMotionActive() &&
      (correctionPhase == CORRECTION_APPLYING ||
       correctionPhase == CORRECTION_RESTORING);
  stopTilt(reason);
  stopHeightNow(reason);
  if (interruptedCorrection) {
    markCorrectionFault(reason);
  }
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
  Serial.print(F(" CORRECTION_TYPE="));
  printCorrectionType(correctionType);
  Serial.print(F(" CORRECTION_PHASE="));
  printCorrectionPhase(correctionPhase);
  Serial.print(F(" CURRENT="));
  Serial.print(analogRead(PIN_CURRENT_SENSOR));
  Serial.print(F(" ESTOP="));
  Serial.print(emergencyStopActive() ? 1 : 0);
  Serial.print(F(" WATCHDOG_MS="));
  Serial.println(COMMAND_WATCHDOG_MS);
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
  Serial.println(F("ERR HOME_LIMIT_NOT_CONFIGURED"));
}

bool startTiltMoveMm(float targetMm,
                     const __FlashStringHelper *acceptedCommand) {
  if (!tiltZeroSet) {
    Serial.println(F("ERR TILT_ZERO_NOT_SET"));
    return false;
  }
  if (tiltMode != TILT_IDLE) {
    Serial.println(F("ERR BUSY_TILT"));
    return false;
  }
  if (heightMode != HEIGHT_STOPPED) {
    Serial.println(F("ERR BUSY_HEIGHT"));
    return false;
  }
  if (emergencyStopActive()) {
    Serial.println(F("ERR EMERGENCY_ACTIVE"));
    return false;
  }
  if (!isfinite(targetMm) || targetMm < 0.0f ||
      targetMm > TILT_MAX_TRAVEL_MM) {
    Serial.println(F("ERR TILT_RANGE"));
    return false;
  }

  tiltTargetSteps = mmToSteps(targetMm);
  if (tiltTargetSteps == tiltPositionSteps) {
    Serial.print(F("DONE "));
    Serial.println(acceptedCommand);
    return true;
  }

  const bool movingUp = tiltTargetSteps > tiltPositionSteps;

  const uint8_t directionLevel =
      movingUp ? TILT_UP_DIR_LEVEL : (TILT_UP_DIR_LEVEL == HIGH ? LOW : HIGH);
  digitalWrite(PIN_DIR, directionLevel);

  tiltMode = TILT_WAITING;
  if (correctionType == CORRECTION_TURTLE_NECK &&
      correctionPhase == CORRECTION_APPLYING) {
    tiltStepIntervalUs = durationToStepIntervalUs(
        tiltTargetSteps - tiltPositionSteps, AUTO_TILT_UP_MS);
  } else if (correctionType == CORRECTION_TURTLE_NECK &&
             correctionPhase == CORRECTION_RESTORING) {
    tiltStepIntervalUs = durationToStepIntervalUs(
        tiltTargetSteps - tiltPositionSteps, AUTO_TILT_DOWN_MS);
  } else {
    tiltStepIntervalUs = speedToStepIntervalUs(TILT_SPEED_MM_PER_SEC);
  }
  tiltMotionStartedMs = millis();
  Serial.print(F("OK "));
  Serial.println(acceptedCommand);
  return true;
}

void updateTilt() {
  if (tiltMode == TILT_IDLE) {
    return;
  }

  if (tiltMode == TILT_WAITING) {
    if (millis() - tiltMotionStartedMs < TILT_START_DELAY_MS) {
      return;
    }
    tiltMode = TILT_MOVING;
    tiltMotionStartedMs = millis();
    lastTiltStepUs = micros();
    return;
  }

  if (millis() - tiltMotionStartedMs > TILT_MOTION_TIMEOUT_MS) {
    stopTilt(F("TIMEOUT"));
    Serial.println(F("ERR TILT_TIMEOUT"));
    markCorrectionFault(F("TILT_TIMEOUT"));
    return;
  }

  const bool movingUp = tiltTargetSteps > tiltPositionSteps;

  const unsigned long nowUs = micros();
  if ((unsigned long)(nowUs - lastTiltStepUs) < tiltStepIntervalUs) {
    return;
  }
  lastTiltStepUs = nowUs;

  digitalWrite(PIN_STEP, HIGH);
  delayMicroseconds(STEP_PULSE_US);
  digitalWrite(PIN_STEP, LOW);

  tiltPositionSteps += movingUp ? 1 : -1;
  if (tiltPositionSteps == tiltTargetSteps) {
    stopTilt(F("TARGET"));
    Serial.println(F("DONE TILT"));
    finishCorrectionMotion();
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

bool startHeight(HeightMode direction, unsigned long requestedMs) {
  if (tiltMode != TILT_IDLE) {
    Serial.println(F("ERR BUSY_TILT"));
    return false;
  }
  // 기울기가 기준 위치(0 mm)가 아니면 높이 축은 어떤 경우에도 구동하지 않는다.
  if (!tiltAtHeightSafeReference()) {
    Serial.println(F("ERR HEIGHT_BLOCKED_TILT_NOT_HOME"));
    return false;
  }
  if (heightMode != HEIGHT_STOPPED) {
    Serial.println(F("ERR BUSY_HEIGHT"));
    return false;
  }
  if (emergencyStopActive()) {
    Serial.println(F("ERR EMERGENCY_ACTIVE"));
    return false;
  }
  if (requestedMs == 0 || requestedMs > ACTUATOR_MAX_RUN_MS) {
    Serial.println(F("ERR HEIGHT_TIME_RANGE"));
    return false;
  }
  setHeightDirection(direction);
  heightMode = direction;
  heightTravelDirection = direction;
  heightRequestedRunMs = requestedMs;
  heightMotionStartedMs = millis();
  lastCurrentSampleMs = millis();
  overcurrentSamples = 0;
  Serial.println(F("OK HEIGHT"));
  return true;
}

void startSafetyReversePause() {
  if (emergencyStopActive()) {
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
  Serial.println(F("OK SAFETY_REVERSE"));
}

void updateHeight() {
  if (heightMode == HEIGHT_STOPPED) {
    return;
  }

  if ((heightMode == HEIGHT_UP || heightMode == HEIGHT_DOWN) &&
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
      markCorrectionFault(F("OVERCURRENT"));
      if (wasMovingUp) {
        startSafetyReversePause();
      }
      return;
    }
  }

  if ((heightMode == HEIGHT_UP || heightMode == HEIGHT_DOWN) &&
      millis() - heightMotionStartedMs >= heightRequestedRunMs) {
    stopHeightNow(F("TIME"));
    Serial.println(F("DONE HEIGHT"));
    finishCorrectionMotion();
    return;
  } else if (heightMode == HEIGHT_SAFETY_PAUSE &&
             millis() - heightMotionStartedMs >= SAFETY_REVERSE_PAUSE_MS) {
    if (emergencyStopActive()) {
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

}

// ---------------------- 자세 교정 및 원위치 복귀 -------------------------

bool rejectIfCorrectionLocked() {
  if (correctionPhase == CORRECTION_IDLE) {
    return false;
  }
  Serial.println(F("ERR CORRECTION_LOCKED"));
  return true;
}

void startPostureCorrection(CorrectionType requestedType) {
  if (correctionPhase != CORRECTION_IDLE) {
    Serial.println(F("ERR CORRECTION_LOCKED"));
    return;
  }
  if (anyMotionActive()) {
    Serial.println(F("ERR BUSY"));
    return;
  }

  // 두 자동 교정 모두 안전 기준 위치인 기울기 0 mm에서만 시작한다.
  if (!tiltAtHeightSafeReference()) {
    Serial.println(F("ERR CORRECTION_REQUIRES_TILT_HOME"));
    return;
  }

  correctionType = requestedType;
  correctionPhase = CORRECTION_APPLYING;
  correctionStartTiltSteps = tiltPositionSteps;

  bool started = false;
  if (requestedType == CORRECTION_TURTLE_NECK) {
    // 거북목: 상판을 사용자 쪽으로 기울여 고개를 덜 숙이게 한다.
    const float targetMm =
        stepsToMm(correctionStartTiltSteps) + AUTO_TILT_DELTA_MM;
    started = startTiltMoveMm(targetMm,
                              F("CORRECTION_TURTLE_NECK"));
  } else if (requestedType == CORRECTION_BENT_BACK) {
    // 굽은 허리: 책상이 낮다고 보고 높이를 제한된 시간만 올린다.
    started = startHeight(HEIGHT_UP, AUTO_HEIGHT_UP_MS);
  }

  if (!started) {
    correctionType = CORRECTION_NONE;
    correctionPhase = CORRECTION_IDLE;
    correctionStartTiltSteps = 0;
    Serial.println(F("ERR CORRECTION_NOT_STARTED"));
    return;
  }

  if (!anyMotionActive()) {
    finishCorrectionMotion();
  }
}

void startRestore() {
  if (correctionPhase != CORRECTION_APPLIED) {
    Serial.println(F("ERR RESTORE_NOT_READY"));
    return;
  }
  if (anyMotionActive()) {
    Serial.println(F("ERR BUSY"));
    return;
  }

  correctionPhase = CORRECTION_RESTORING;
  bool started = false;
  if (correctionType == CORRECTION_TURTLE_NECK) {
    // 교정 시작 때 기억한 스텝 위치로 정확히 같은 거리만큼 되돌아간다.
    started = startTiltMoveMm(stepsToMm(correctionStartTiltSteps),
                              F("RESTORE_TILT"));
  } else if (correctionType == CORRECTION_BENT_BACK) {
    // 위치 센서가 없으므로 올린 시간과 같은 시간만큼 하강한다.
    started = startHeight(HEIGHT_DOWN, AUTO_HEIGHT_DOWN_MS);
  }

  if (!started) {
    correctionPhase = CORRECTION_APPLIED;
    Serial.println(F("ERR RESTORE_NOT_STARTED"));
    return;
  }

  if (!anyMotionActive()) {
    finishCorrectionMotion();
  }
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

  // N=Normal, W=Warning, C <posture>=Critical, H=Heartbeat, R=Restore.
  if (strcmp(command, "C") == 0) {
    char *posture = strtok(NULL, " \t");
    if (posture == NULL || strtok(NULL, " \t") != NULL) {
      Serial.println(F("ERR C_ARGUMENT"));
      return;
    }
    uppercase(posture);
    markValidCommand();
    if (strcmp(posture, "TURTLE_NECK") == 0) {
      startPostureCorrection(CORRECTION_TURTLE_NECK);
    } else if (strcmp(posture, "BENT_BACK") == 0) {
      startPostureCorrection(CORRECTION_BENT_BACK);
    } else {
      Serial.println(F("ERR C_POSTURE"));
    }
    return;
  }

  if (strcmp(command, "R") == 0) {
    markValidCommand();
    startRestore();
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
    if (rejectIfCorrectionLocked()) {
      return;
    }
    markValidCommand();
    setTiltZero();
    return;
  }

  if (strcmp(command, "HOME") == 0) {
    if (rejectIfCorrectionLocked()) {
      return;
    }
    markValidCommand();
    startTiltHome();
    return;
  }

  if (strcmp(command, "TILT") == 0) {
    if (rejectIfCorrectionLocked()) {
      return;
    }
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
    if (rejectIfCorrectionLocked()) {
      return;
    }
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
    if (rejectIfCorrectionLocked()) {
      return;
    }
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
  pinMode(PIN_ACTUATOR_IN1, OUTPUT);
  pinMode(PIN_ACTUATOR_IN2, OUTPUT);

  pinMode(PIN_EMERGENCY_STOP, INPUT_PULLUP);

  digitalWrite(PIN_STEP, LOW);
  stopHeightNow(F("BOOT"));

  Serial.begin(9600);
  lastValidCommandMs = millis();

  // 별도 원점 센서가 없으므로 부팅 위치를 소프트웨어 0점으로 둔다.
  tiltZeroSet = true;
  tiltPositionSteps = 0;
  tiltTargetSteps = 0;

  Serial.println(F("READY SMART_POSTURE_DESK_V5_NWCHR"));
  Serial.println(F("INFO TILT_ZERO_FROM_BOOT"));
}

void loop() {
  readSerialCommands();

  if (emergencyStopActive() && anyMotionActive()) {
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

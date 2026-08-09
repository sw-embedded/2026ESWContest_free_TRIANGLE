/*
 * 스마트 자세 교정 책상 - Arduino Uno R3 모터 제어기
 * 외부 리미트 스위치와 비상 정지 기능이 없는 초기 시제품 버전
 *
 * 사용 하드웨어
 *   - A4988 + NEMA17 17HS3401S-T8x8 (T8 리드스크루, 회전당 8mm 이동)
 *   - L298N + 12V 리니어 액추에이터
 *
 * 라즈베리파이 통신: USB 시리얼, 9600 baud, 줄바꿈 문자로 명령 종료
 * 배선하거나 시험하기 전에 같은 폴더의 README.md를 확인할 것
 */

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

// ----------------------------- 핀 배치 ---------------------------------

const uint8_t PIN_STEP = 2;
const uint8_t PIN_DIR = 3;
const uint8_t PIN_STEP_ENABLE = 4;  // A4988 ENABLE 핀, LOW일 때 활성화

const uint8_t PIN_ACTUATOR_PWM = 5; // L298N ENA 핀(ENA 점퍼를 제거하고 연결)
const uint8_t PIN_ACTUATOR_IN1 = 6;
const uint8_t PIN_ACTUATOR_IN2 = 7;

// D8~D12는 현재 사용하지 않는다.
// 추후 리미트 스위치와 비상 정지 입력을 연결하기 위해 비워둔 핀이다.

// --------------------------- 기구 설정 ---------------------------------

const float MOTOR_FULL_STEPS_PER_REV = 200.0f; // 스텝각이 1.8도인 모터
const float MICROSTEPS = 8.0f;                  // A4988 설정: MS1=HIGH, MS2=HIGH, MS3=LOW
const float LEAD_SCREW_MM_PER_REV = 8.0f;       // T8x8 리드스크루는 한 바퀴에 8mm 이동
const float TILT_STEPS_PER_MM =
    (MOTOR_FULL_STEPS_PER_REV * MICROSTEPS) / LEAD_SCREW_MM_PER_REV;

// HIGH일 때 리드스크루 너트가 상판을 올리는 방향으로 움직여야 한다.
// 실제 기구가 반대 방향으로 움직이면 HIGH를 LOW로 변경한다.
const uint8_t TILT_UP_DIR_LEVEL = HIGH;

// SET_ZERO로 저장한 위치를 기준으로 적용되는 소프트웨어상의 이동 한계이다.
// 실제 기구의 이동 가능 거리를 측정하고, 처음 시험할 때는 훨씬 작은 값부터 사용한다.
const float TILT_MAX_TRAVEL_MM = 100.0f;
const float TILT_SPEED_MM_PER_SEC = 4.0f;

// src/main.py sends A without a distance, so keep its correction target in one
// configurable constant. Calibrate this conservatively for the real mechanism.
const float AUTO_TILT_TARGET_MM = 5.0f;

// 정격 속도 기준 전체 스트로크 작동시간: 100mm / 9.5mm/s = 10,526.32ms
// 이론상 100mm 이동이 중간에 끊기지 않도록 밀리초 단위에서 올림한다.
// 실제 이동 속도는 하중이나 L298N의 전압 강하 때문에 더 느릴 수 있다.
const unsigned long ACTUATOR_MAX_RUN_MS = 10527UL;
const uint8_t ACTUATOR_TEST_PWM = 180;

// 모터가 움직이는 동안 라즈베리파이는 PING 명령을 계속 보내야 한다.
const unsigned long COMMAND_WATCHDOG_MS = 3000UL;
const unsigned long TILT_MOTION_TIMEOUT_MS = 30000UL;
const uint8_t STEP_PULSE_US = 3;

// ----------------------------- 동작 상태 --------------------------------

enum TiltMode {
  TILT_IDLE,
  TILT_MOVING
};

enum HeightMode {
  HEIGHT_STOPPED,
  HEIGHT_UP,
  HEIGHT_DOWN
};

TiltMode tiltMode = TILT_IDLE;
HeightMode heightMode = HEIGHT_STOPPED;

long tiltPositionSteps = 0;
long tiltTargetSteps = 0;
bool tiltZeroSet = false;

unsigned long tiltStepIntervalUs = 0;
unsigned long lastTiltStepUs = 0;
unsigned long tiltMotionStartedMs = 0;
unsigned long heightMotionStartedMs = 0;
unsigned long heightRequestedRunMs = 0;
unsigned long lastValidCommandMs = 0;

const size_t COMMAND_BUFFER_SIZE = 64;
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;

// --------------------------- 공통 함수 ----------------------------------

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
  enableStepper(false);

  if (wasMoving) {
    Serial.print(F("TILT_STOP "));
    Serial.println(reason);
  }
}

void stopHeight(const __FlashStringHelper *reason) {
  const bool wasMoving = heightMode != HEIGHT_STOPPED;
  analogWrite(PIN_ACTUATOR_PWM, 0);
  digitalWrite(PIN_ACTUATOR_IN1, LOW);
  digitalWrite(PIN_ACTUATOR_IN2, LOW);
  heightMode = HEIGHT_STOPPED;

  if (wasMoving) {
    Serial.print(F("HEIGHT_STOP "));
    Serial.println(reason);
  }
}

void stopAll(const __FlashStringHelper *reason) {
  stopTilt(reason);
  stopHeight(reason);
}

void printStatus() {
  Serial.print(F("STATUS TILT_ZERO_SET="));
  Serial.print(tiltZeroSet ? 1 : 0);
  Serial.print(F(" TILT_MM="));
  Serial.print(stepsToMm(tiltPositionSteps), 2);
  Serial.print(F(" TILT_MODE="));
  Serial.print((int)tiltMode);
  Serial.print(F(" HEIGHT_MODE="));
  Serial.println((int)heightMode);
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

void startTiltMoveMm(float targetMm,
                     const __FlashStringHelper *acceptedCommand) {
  if (!tiltZeroSet) {
    Serial.println(F("ERR TILT_ZERO_NOT_SET"));
    return;
  }
  if (heightMode != HEIGHT_STOPPED) {
    Serial.println(F("ERR BUSY_HEIGHT"));
    return;
  }
  if (targetMm < 0.0f || targetMm > TILT_MAX_TRAVEL_MM) {
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
  const uint8_t directionLevel = movingUp ? TILT_UP_DIR_LEVEL : !TILT_UP_DIR_LEVEL;
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

  const unsigned long nowUs = micros();
  if ((unsigned long)(nowUs - lastTiltStepUs) < tiltStepIntervalUs) {
    return;
  }
  lastTiltStepUs = nowUs;

  const bool movingUp = tiltTargetSteps > tiltPositionSteps;
  digitalWrite(PIN_STEP, HIGH);
  delayMicroseconds(STEP_PULSE_US);
  digitalWrite(PIN_STEP, LOW);
  tiltPositionSteps += movingUp ? 1 : -1;

  if (tiltPositionSteps == tiltTargetSteps) {
    stopTilt(F("TARGET"));
    Serial.println(F("DONE TILT"));
  }
}

// ---------------------------- 높이 제어 ---------------------------------

void startHeight(HeightMode direction, unsigned long requestedMs) {
  if (tiltMode != TILT_IDLE) {
    Serial.println(F("ERR BUSY_TILT"));
    return;
  }
  if (requestedMs == 0 || requestedMs > ACTUATOR_MAX_RUN_MS) {
    Serial.println(F("ERR HEIGHT_TIME_RANGE"));
    return;
  }

  heightMode = direction;
  heightRequestedRunMs = requestedMs;
  heightMotionStartedMs = millis();

  if (direction == HEIGHT_UP) {
    digitalWrite(PIN_ACTUATOR_IN1, HIGH);
    digitalWrite(PIN_ACTUATOR_IN2, LOW);
  } else {
    digitalWrite(PIN_ACTUATOR_IN1, LOW);
    digitalWrite(PIN_ACTUATOR_IN2, HIGH);
  }
  analogWrite(PIN_ACTUATOR_PWM, ACTUATOR_TEST_PWM);
  Serial.println(F("OK HEIGHT"));
}

void updateHeight() {
  if (heightMode == HEIGHT_STOPPED) {
    return;
  }

  if (millis() - heightMotionStartedMs >= heightRequestedRunMs) {
    stopHeight(F("TIME"));
    Serial.println(F("DONE HEIGHT"));
  }
}

// ------------------------- 시리얼 통신 처리 ------------------------------

void uppercase(char *text) {
  while (*text != '\0') {
    *text = (char)toupper((unsigned char)*text);
    ++text;
  }
}

void handleCommand(char *line) {
  char *command = strtok(line, " \t");
  if (command == NULL) {
    return;
  }
  uppercase(command);
  lastValidCommandMs = millis();

  // Raspberry Pi src/main.py compatibility: "A\n" starts correction and
  // "S\n" stops all motion.
  if (strcmp(command, "A") == 0) {
    startTiltMoveMm(AUTO_TILT_TARGET_MM, F("A"));
    return;
  }

  if (strcmp(command, "S") == 0) {
    stopAll(F("COMMAND"));
    Serial.println(F("OK S"));
    return;
  }

  if (strcmp(command, "STOP") == 0) {
    stopAll(F("COMMAND"));
    Serial.println(F("OK STOP"));
    return;
  }

  if (strcmp(command, "PING") == 0 || strcmp(command, "KEEPALIVE") == 0) {
    Serial.println(F("PONG"));
    return;
  }

  if (strcmp(command, "STATUS") == 0) {
    printStatus();
    return;
  }

  if (strcmp(command, "SET_ZERO") == 0) {
    setTiltZero();
    return;
  }

  if (strcmp(command, "HOME") == 0) {
    Serial.println(F("ERR HOME_REQUIRES_LIMIT_SWITCH"));
    return;
  }

  if (strcmp(command, "TILT") == 0) {
    char *value = strtok(NULL, " \t");
    if (value == NULL) {
      Serial.println(F("ERR TILT_ARGUMENT"));
      return;
    }
    char *end = NULL;
    const float targetMm = (float)strtod(value, &end);
    if (end == value || *end != '\0') {
      Serial.println(F("ERR TILT_ARGUMENT"));
      return;
    }
    startTiltMoveMm(targetMm, F("TILT"));
    return;
  }

  if (strcmp(command, "TILT_REL") == 0) {
    char *value = strtok(NULL, " \t");
    if (value == NULL || !tiltZeroSet) {
      Serial.println(F("ERR TILT_REL_ARGUMENT"));
      return;
    }
    char *end = NULL;
    const float deltaMm = (float)strtod(value, &end);
    if (end == value || *end != '\0') {
      Serial.println(F("ERR TILT_REL_ARGUMENT"));
      return;
    }
    startTiltMoveMm(stepsToMm(tiltPositionSteps) + deltaMm, F("TILT"));
    return;
  }

  if (strcmp(command, "HEIGHT") == 0) {
    char *direction = strtok(NULL, " \t");
    char *duration = strtok(NULL, " \t");
    if (direction == NULL || duration == NULL) {
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
      startHeight(HEIGHT_UP, durationMs);
    } else if (strcmp(direction, "DOWN") == 0) {
      startHeight(HEIGHT_DOWN, durationMs);
    } else {
      Serial.println(F("ERR HEIGHT_DIRECTION"));
    }
    return;
  }

  Serial.println(F("ERR UNKNOWN_COMMAND"));
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    const char incoming = (char)Serial.read();

    if (incoming == '\r') {
      continue;
    }
    if (incoming == '\n') {
      commandBuffer[commandLength] = '\0';
      handleCommand(commandBuffer);
      commandLength = 0;
      continue;
    }

    if (commandLength < COMMAND_BUFFER_SIZE - 1) {
      commandBuffer[commandLength++] = incoming;
    } else {
      commandLength = 0;
      Serial.println(F("ERR COMMAND_TOO_LONG"));
    }
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

  digitalWrite(PIN_STEP, LOW);
  enableStepper(false);
  stopHeight(F("BOOT"));

  Serial.begin(9600);
  lastValidCommandMs = millis();
  Serial.println(F("READY SMART_POSTURE_DESK_V2_NO_LIMITS"));
  Serial.println(F("INFO SEND_SET_ZERO_BEFORE_TILT"));
}

void loop() {
  readSerialCommands();

  if (anyMotionActive() &&
      millis() - lastValidCommandMs > COMMAND_WATCHDOG_MS) {
    stopAll(F("WATCHDOG"));
    Serial.println(F("ERR WATCHDOG"));
  }

  updateTilt();
  updateHeight();
}

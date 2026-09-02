# 스마트 자세 교정 데스크 시스템

**Team TRIANGLE**

카메라로 사용자의 상체 자세를 인식하고, 거북목이나 굽은 등을 일정 시간 감지하면
책상의 기울기 또는 높이를 자동으로 조절하는 임베디드 시스템입니다. Raspberry Pi는
AI 자세 인식과 전체 제어를 담당하고, Arduino Uno는 모터와 안전 입력을 담당합니다.

## 개발 배경과 목표

장시간 책상 작업에서는 목이 앞으로 빠지거나 허리가 굽은 상태가 오랫동안 유지되기
쉽습니다. 일반적인 알림 방식은 사용자가 직접 자세를 바꾸어야 하므로 경고를 놓치거나
무시할 수 있습니다. 이 프로젝트는 자세를 감지하는 데서 끝나지 않고 책상 자체가
제한된 범위 안에서 반응하도록 구성했습니다.

목표는 다음 세 가지입니다.

- 카메라 한 대로 사용자의 목과 몸통 자세를 지속적으로 판정합니다.
- 순간적인 움직임에는 반응하지 않고 같은 불량 자세가 일정 시간 이어질 때만 동작합니다.
- Raspberry Pi의 판단과 Arduino의 모터·안전 제어를 분리해 구동 중에도 안전 입력을
  계속 확인합니다.

## 주요 기능

| 기능 | 내용 |
|---|---|
| 자세 인식 | MoveNet SinglePose Thunder로 17개 관절 좌표 추출 |
| 자세 판정 | 귀·어깨·골반 좌표로 목과 몸통의 2D 각도 계산 |
| 오차 완화 | EMA 필터로 프레임별 목·몸통 각도의 흔들림 완화 |
| 자동 교정 | 같은 불량 자세가 60초 유지되면 책상 기울기 또는 높이 조절 |
| 자동 복귀 | 교정 후 정상 자세가 300초 유지되면 원래 위치로 복귀 |
| 상태 확인 | 웹 대시보드에서 자세, 각도, 교정 상태와 Arduino 상태 표시 |
| 안전 제어 | 비상정지, 과전류 감지, 3초 통신 Watchdog 적용 |

## 시스템 구성

```text
Raspberry Pi Camera
  → Picamera2 RGB888 프레임
  → MoveNet TFLite 자세 추론
  → 목·몸통 각도 계산 및 자세 판정
  → 자세 유지 시간 확인
  → USB Serial 명령 전송
  → Arduino Uno
  → A4988/NEMA17 기울기 제어
  → L298N/리니어 액추에이터 높이 제어
```

Raspberry Pi와 Arduino는 9600 baud USB 시리얼로 연결됩니다. Raspberry Pi는
2초마다 heartbeat를 전송하고 1초마다 Arduino 상태를 요청합니다.

### 구성 요소별 역할

| 구성 요소 | 역할 |
|---|---|
| Raspberry Pi Camera | 사용자의 상체가 포함된 RGB 프레임 획득 |
| Raspberry Pi 4 | MoveNet 추론, 각도 계산, 자세 유지 시간과 교정 시점 판단 |
| Arduino Uno R3 | 시리얼 명령 해석, 모터 상태 머신, 안전 입력 감시 |
| A4988 + NEMA17 | 리드스크루를 움직여 책상 상판 기울기 조절 |
| L298N + 리니어 액추에이터 | 책상 높이 상승·하강 |
| Flask 대시보드 | 현재 자세, 각도, 교정 단계와 Arduino 상태 표시 |

## 코드 구동 흐름

실행 진입점은 `src/main.py`입니다.

1. `config/default.yaml`에서 카메라, 자세 임계값, 시리얼 설정을 읽습니다.
2. Flask 웹 서버와 단일 시리얼 worker를 별도 thread로 시작합니다.
3. Picamera2에서 기본 640×480 `RGB888` 프레임을 가져옵니다.
4. 프레임 비율을 유지한 채 resize하고 검은색 letterbox padding을 적용합니다.
5. MoveNet 출력 `[1, 1, 17, 3]`에서 17개 `(y, x, score)` 좌표를 추출합니다.
6. 신뢰도가 높은 좌우 귀·어깨·골반을 선택해 목과 몸통 각도를 계산합니다.
7. 자세 상태와 유지 시간을 바탕으로 Arduino에 교정·정지·복귀 명령을 보냅니다.
8. 자세와 Arduino 상태를 `/api/status`에 합쳐 웹 화면에 표시합니다.

교정 또는 복귀 모터가 움직이는 동안에는 `N` 명령을 보내지 않습니다. 교정이
완료된 `APPLIED` 상태에서 정상 자세가 300초 연속 유지될 때만 `R` 명령을 한 번
전송하며, 중간에 자세가 바뀌면 복귀 대기 시간은 초기화됩니다.

### 1. 프레임 전처리와 MoveNet 추론

`PoseDetector`는 설정된 모델 이름으로 `models/` 안의 TFLite 파일을 불러옵니다.
모델 파일에서 입력 크기와 자료형을 직접 읽고, 입력이
`(1, size, size, 3)`, 출력이 `(1, 1, 17, 3)` 형태인지 확인합니다.

카메라 프레임은 원본 비율을 유지한 채 모델 입력 크기에 맞게 축소한 다음, 남는
영역을 검은색으로 채웁니다. 이때 사용한 배율과 좌우·상하 여백을 함께 반환해
MoveNet 좌표를 원본 프레임 좌표로 되돌릴 때 사용합니다. 모델 입력 자료형이
`uint8`이면 픽셀값을 그대로 사용하고, 그 외에는 `float32`로 변환한 뒤 255로
나눕니다.

### 2. 목·몸통 각도 계산

17개 관절 중 양쪽 귀, 어깨, 골반을 사용합니다. 먼저 오른쪽과 왼쪽 각각의
귀·어깨·골반 신뢰도 합을 비교하고 더 선명하게 인식된 쪽을 선택합니다. 귀와
어깨 신뢰도가 `min_visibility`보다 낮으면 `POSE_LOST`로 처리합니다.

선택한 측면의 귀 좌표를 $E=(E_x,E_y)$, 어깨 좌표를
$S=(S_x,S_y)$, 골반 좌표를 $H=(H_x,H_y)$라고 정의합니다. 영상 좌표계는
오른쪽이 +x, 아래쪽이 +y 방향입니다.

거북목 판정에는 귀와 어깨의 상대 위치로 구한 CVA 기반 전방 목 기울기
$\theta_{neck}$를 사용합니다.

```math
\theta_{neck}
= \max\left(0,
\mathrm{atan2}\left(E_x-S_x,\;S_y-E_y\right)
\times \frac{180}{\pi}\right)
```

즉, 귀가 어깨보다 앞쪽으로 이동할수록 목 각도가 커집니다. `atan2`를 사용해
분모가 0에 가까운 경우도 안전하게 계산하며, 반대 방향으로 기울어 계산값이
음수가 되면 0°로 제한합니다. 귀가 어깨보다 아래에 있는 비정상적인 좌표는
유효한 전방 기울기로 보지 않고 0°로 처리합니다.

굽은 등 판정에는 어깨와 골반을 연결한 몸통 중심선이 수직선에서 벗어난 각도
$\theta_{back}$를 사용합니다.

```math
\theta_{back}
= \mathrm{atan2}\left(\left|H_x-S_x\right|,
\left|H_y-S_y\right|\right)
\times \frac{180}{\pi}
```

좌우 어느 측면이 선택되어도 같은 크기의 기울기를 얻도록 좌표 차이에는 절댓값을
적용합니다. 몸통이 수직에 가까우면 0°에 가깝고, 앞으로 굽을수록 각도가
커집니다.

계산된 두 각도에는 다음 EMA를 적용해 순간적인 흔들림을 줄입니다.

```math
\theta_t^{EMA}
= \alpha\theta_t+(1-\alpha)\theta_{t-1}^{EMA}
```

기본 `alpha`는 0.3입니다. 목 각도가 임계값 이상이면 `TURTLE_NECK`을 우선
판정하고, 그렇지 않으면서 골반이 인식되고 몸통 각도가 임계값 이상이면
`BENT_BACK`으로 판정합니다.

### 3. 자세 유지 시간과 명령 조정

`BadPostureHoldTimer`는 같은 불량 자세가 연속된 시간만 누적합니다. 정상 자세나
`POSE_LOST`가 들어오거나 다른 불량 자세로 바뀌면 누적 시간이 초기화됩니다.
60초가 채워지면 같은 자세에 대해 교정 요청을 한 번만 만듭니다.

`PostureCommandCoordinator`는 자세 판정과 Arduino 교정 상태를 함께 확인합니다.
전송 실패한 교정·복귀 요청은 다음 순환에서 다시 시도하지만, 자세가 바뀐 오래된
교정 요청은 버립니다. `APPLYING`과 `RESTORING` 중에는 정상 자세가 감지되어도
`N`을 보내지 않아 진행 중인 모터 동작이 중단되지 않도록 합니다.

### 4. 교정 상태 전이

| 단계 | 의미 | 다음 동작 |
|---|---|---|
| `IDLE` | 적용된 교정이 없는 대기 상태 | 새로운 교정 명령 수신 가능 |
| `APPLYING` | 기울기 또는 높이 교정 진행 중 | 완료되면 `APPLIED` 전환 |
| `APPLIED` | 교정 위치 유지 | 정상 자세 300초 후 `R` 요청 |
| `RESTORING` | 교정 전 위치로 복귀 중 | 완료되면 `IDLE` 전환 |
| `FAULT` | 자동 구동이 안전 조건에 의해 중단됨 | 새로운 자동 교정을 차단하고 오류 상태 표시 |

## 자세 판정과 책상 동작

| 자세 상태 | 기본 조건 | 동작 |
|---|---|---|
| `TURTLE_NECK` | 목 각도 22° 이상이 60초 유지 | NEMA17로 상판 기울기 +5 mm 이동 |
| `BENT_BACK` | 몸통 각도 15° 이상이 60초 유지 | 리니어 액추에이터로 높이 4초 상승 |
| `NORMAL` | 불량 자세 조건에 해당하지 않음 | 교정 후 300초 유지 시 원위치 복귀 |
| `POSE_LOST` | 필요한 관절 좌표의 신뢰도 부족 | 새로운 교정 명령을 보내지 않음 |

임계값과 유지 시간은 `config/default.yaml`에서 변경할 수 있습니다.

## 모터 제어 방식

### 거북목 교정

Arduino는 교정 시작 시점의 스텝 위치를 저장합니다. 4초의 비차단 대기 후 A4988에
STEP 펄스를 보내 NEMA17을 구동하고, 기본 설정에서는 상판을 +5 mm 이동시킵니다.
복귀할 때에는 저장해 둔 시작 스텝 위치로 되돌아갑니다. 기울기 위치는
0~100 mm의 소프트웨어 범위와 30초 동작 제한을 적용합니다.

### 굽은 등 교정

상판 기울기가 소프트웨어 기준 0 mm일 때만 높이 축을 움직일 수 있습니다.
`BENT_BACK` 교정에서는 L298N의 IN1/IN2로 액추에이터를 4초 동안 상승시킵니다.
복귀 명령을 받으면 위치 센서 대신 동일한 4초 동안 하강합니다. 기울기 축과 높이
축은 동시에 움직일 수 없습니다.

별도 원점 센서가 없으므로 Arduino는 부팅 위치를 기울기 0 mm로 설정합니다.

## Arduino 핀 구성

| Arduino Uno | 연결 |
|---|---|
| D2 | A4988 DIR |
| D3 | A4988 STEP |
| D4 | 미사용, A4988 ENABLE은 LOW 고정 |
| D5 | 미사용, L298N ENA는 점퍼 연결 |
| D6 | 미사용 |
| D7 | L298N IN1 |
| D8 | L298N IN2 |
| D9-D11 | 미사용 |
| D12 | 비상정지 스위치, `INPUT_PULLUP`, Active-LOW |
| A0 | 전류 센서 |

Arduino가 3초 동안 유효한 명령을 받지 못하거나 D12 비상정지 또는 과전류를
감지하면 모든 구동을 정지합니다.

### 안전 제어 우선순위

- D12 비상정지가 LOW가 되면 STEP 출력을 멈추고 L298N의 IN1/IN2를 LOW로 만듭니다.
- A0 전류값이 기준값을 10 ms 간격으로 3회 연속 넘으면 과전류로 판단합니다.
- 상승 중 과전류가 발생하면 100 ms 정지 후 300 ms만 하강 방향으로 움직입니다.
- 모터가 움직이는 동안 유효한 시리얼 명령이 3초 이상 없으면 Watchdog이 정지시킵니다.
- 자동 교정이 중단되면 `FAULT`로 전환해 추가 자동 구동을 막습니다.

비상정지는 `INPUT_PULLUP`을 사용하므로 버튼이 눌릴 때 D12가 GND와 연결되어야
합니다. 소프트웨어 안전 기능은 별도의 물리 전원 차단 장치를 대체하지 않습니다.

## 시리얼 명령

| 명령 | Arduino 동작 |
|---|---|
| `H` | heartbeat 갱신 및 `PONG` 응답 |
| `STATUS` | 모터·교정·센서·Watchdog 상태 반환 |
| `N` | 모터 정지 및 정상 자세 상태 반영 |
| `C TURTLE_NECK` | 기울기 교정 시작 |
| `C BENT_BACK` | 높이 교정 시작 |
| `R` | 적용된 교정을 원래 위치로 복귀 |
| `STOP` | 모든 모터 즉시 정지 |

모든 명령은 LF(`\n`)로 끝나는 ASCII 문자열로 전송합니다.

`SerialController`의 단일 worker만 시리얼 포트를 소유합니다. 자세 처리 루프와
웹 서버는 포트를 직접 열지 않고 같은 상태 객체를 공유하므로 포트 중복 접근을
방지합니다. Arduino 응답이 기본 10초 동안 없으면 연결 끊김으로 표시하고 재연결을
시도합니다.

## 주요 설정값

| 설정 경로 | 기본값 | 설명 |
|---|---:|---|
| `camera.width`, `camera.height` | 640, 480 | 카메라 프레임 크기 |
| `camera.sample_interval_sec` | 0.05 | 자세 처리 순환 사이 대기 시간 |
| `pose.model` | `thunder` | 사용할 MoveNet 모델 |
| `pose.min_visibility` | 0.05 | 관절 사용 최소 신뢰도 |
| `posture.head_pitch_threshold_deg` | 22.0 | 거북목 판정 목 각도 |
| `posture.torso_angle_threshold_deg` | 15.0 | 굽은 등 판정 몸통 각도 |
| `posture.bad_duration_sec` | 60 | 자동 교정 전 연속 유지 시간 |
| `posture.normal_restore_delay_sec` | 300 | 자동 복귀 전 정상 자세 유지 시간 |
| `actuator.baudrate` | 9600 | Arduino 통신 속도 |
| `actuator.heartbeat_interval_sec` | 2.0 | heartbeat 전송 주기 |
| `actuator.status_interval_sec` | 1.0 | Arduino 상태 요청 주기 |
| `actuator.response_timeout_sec` | 10.0 | 응답 없음 판정 시간 |

## 실행 준비

Raspberry Pi OS에서 다음과 같이 환경을 구성합니다.

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -m pip install -r requirements/raspberrypi.txt
```

MoveNet Thunder 모델은 다음 경로에 둡니다.

```text
models/movenet_singlepose_thunder.tflite
```

모델 다운로드 방법과 SHA-256은 `models/README.md`에 정리되어 있습니다.

Arduino IDE에서 `arduino/desk_controller/desk_controller.ino`를 Arduino Uno에
업로드한 뒤, `config/default.yaml`의 시리얼 포트를 실제 환경에 맞게 설정합니다.

## 실행 방법

```bash
source .venv/bin/activate
python3 src/main.py
```

웹 대시보드는 기본적으로 다음 주소에서 열립니다.

```text
http://<raspberry-pi-ip>:5000/
```

대시보드는 현재 자세, 목·몸통 각도, 갱신 시각, Arduino 연결 상태, 활성 교정,
교정 단계, 기울기 위치, 전류 센서값과 비상정지 상태를 표시합니다. 브라우저는
`/api/status`를 1초마다 요청합니다.

## 주요 폴더

```text
arduino/                    Arduino 모터·안전 제어 펌웨어
config/                     카메라, 자세 판정, 시리얼 설정
docs/                       시스템 구조와 하드웨어 설명
models/                     MoveNet TFLite 모델 위치
requirements/               Raspberry Pi Python 의존성
src/main.py                 전체 시스템 실행 진입점
src/camera/                 Picamera2 프레임 획득
src/pose/                   MoveNet 전처리·추론과 EMA 필터
src/posture/                각도 판정, 유지 시간, 명령 조정
src/actuator/               시리얼 worker와 Arduino 상태 파서
src/monitor/, src/ui/       통합 상태와 Flask 대시보드
```

사용한 오픈소스와 라이선스 정보는 `THIRD_PARTY_NOTICES.md`에 정리되어 있습니다.

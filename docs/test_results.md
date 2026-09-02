# 검증 결과

검증 결과는 **정적 확인**, **자동 테스트**, **실물 확인 필요**를 구분합니다.
근거 파일이 없는 성능 수치는 검증 완료로 취급하지 않습니다.

## 성공한 검사

- Python `compileall`: `src`, `scripts`, `tests` 문법 검사 성공
- Python 단위 테스트: 25개 중 24개 성공, 1개 Flask 미설치로 skip
- 하드웨어/영상 의존성이 없는 actuator, posture, monitor 모듈 import 성공
- Raspberry Pi-Arduino 명령 정적 대조:
  - 9600 baud 일치
  - Raspberry Pi 송신 `H`, `STATUS`, `N`, `C TURTLE_NECK`,
    `C BENT_BACK`, `R`을 Arduino가 모두 처리
  - Raspberry Pi가 모든 명령에 LF를 추가하고 Arduino가 공백/대소문자를 처리
- 최종 진입점에서 `SerialController` 하나를 공유하므로 Flask와 vision loop의
  중복 포트 open 없음
- MediaPipe 코드/의존성 없음
- 추적 파일에서 API key, password, 개인 사용자 절대경로를 찾지 못함
- 전체 Git history의 대표적 secret/개인 절대경로 pattern 검색 결과 0건
- 현재 추적 파일에 영상·음원·이미지·압축 파일이 없고, history 최대 blob은 약 29 KB

## 건너뛰거나 실행하지 못한 검사

- Flask API 테스트 1개: 최초 점검 Python 환경에 Flask가 없어 skip
- pose/UI/camera 모듈 import와 YAML runtime parse: 점검 환경에 OpenCV,
  Flask, Picamera2, PyYAML이 없어 미실행
- Arduino compile: 점검 환경에 Arduino CLI가 없어 미실행
- MoveNet load/inference: `.tflite` 모델과 Raspberry Pi LiteRT 환경이 없어 미실행
- Picamera2 capture: Raspberry Pi/카메라가 연결된 환경이 아니므로 미실행

## 코드 구현은 확인했지만 실물 검증이 필요한 항목

- NEMA17과 리니어 액추에이터 방향, 이동량, 구동 시간
- D12 E-stop 입력과 물리 전원 차단
- A0 전류 센서 장착 여부, 정상/구속 전류, threshold 500
- 과전류 3회 감지와 300 ms 안전 역동작
- 3초 Watchdog과 통신 단절 시 정지

## 근거가 없어 사용하면 안 되는 성능 주장

현재 저장소에는 원시 측정 로그, 실험 설계, 표본 수, 계산 코드가 없습니다. 따라서
PPT의 31.2 FPS, `<120 ms`, 96.8% precision, 100% fail-safe reliability와
기존 문서의 30-40 ms 추론 수치는 재현된 결과로 간주할 수 없습니다.

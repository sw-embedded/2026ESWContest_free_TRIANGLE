# Third-party software and model notices

이 문서는 **스마트 자세 교정 데스크 시스템**(Team TRIANGLE)이 사용하는
외부 모델과 주요 라이브러리의 출처를 기록합니다. 각 항목의 저작권과 라이선스는
원 저작자에게 있으며, 실제 제출/배포 시 사용한 버전의 라이선스 원문을 다시
확인해야 합니다.

| 구성요소 | 사용 목적 | 공식 출처 | 라이선스 |
|---|---|---|---|
| MoveNet SinglePose | 17개 인체 keypoint 추정 | [TensorFlow MoveNet tutorial](https://www.tensorflow.org/hub/tutorials/movenet), [TF Hub Thunder v4](https://tfhub.dev/google/movenet/singlepose/thunder/4) | Apache License 2.0(모델 페이지 기준) |
| LiteRT / ai-edge-litert | Raspberry Pi TFLite 추론 | [google-ai-edge/LiteRT](https://github.com/google-ai-edge/LiteRT) | Apache License 2.0 |
| TensorFlow / tflite-runtime | 선택적 interpreter fallback | [tensorflow/tensorflow](https://github.com/tensorflow/tensorflow) | Apache License 2.0 |
| Picamera2 | Raspberry Pi 카메라 입력 | [raspberrypi/picamera2](https://github.com/raspberrypi/picamera2) | BSD 2-Clause |
| OpenCV | resize/letterbox 영상 전처리 | [opencv/opencv](https://github.com/opencv/opencv) | Apache License 2.0 |
| NumPy | 텐서/배열 처리 | [numpy/numpy](https://github.com/numpy/numpy) | BSD 3-Clause |
| Flask | 상태 대시보드와 REST API | [pallets/flask](https://github.com/pallets/flask) | BSD 3-Clause |
| pySerial | Raspberry Pi-Arduino 통신 | [pyserial/pyserial](https://github.com/pyserial/pyserial) | BSD 3-Clause |
| PyYAML | YAML 설정 읽기 | [yaml/pyyaml](https://github.com/yaml/pyyaml) | MIT |
| Arduino AVR Core | Arduino Uno R3 기본 런타임 | [arduino/ArduinoCore-avr](https://github.com/arduino/ArduinoCore-avr) | 파일별 고지 적용 - 설치한 board package에서 확인 |

## 저장소 고유 구현과 외부 기술의 구분

외부에서 제공되는 부분:

- MoveNet 모델 구조, 학습 가중치와 표준 17-keypoint 출력
- LiteRT/TFLite interpreter, Picamera2, OpenCV, NumPy, Flask, pySerial,
  PyYAML, Arduino core

이 저장소에서 연결·구현한 부분:

- MoveNet keypoint 중 귀·어깨·골반을 이용한 목/몸통 2D 각도 계산
- 각도 EMA, 불량 자세 60초 유지 판정, 자세 상태 정의
- 자세 상태와 `N/W/C/H/R` 시리얼 프로토콜 연결
- Arduino의 기울기/높이 동작, 상태 보고, 복귀, E-stop·전류·시간 제한 로직
- Arduino 상태를 합쳐 보여주는 Flask 상태 API와 대시보드

저장소에서 제3자 예제 소스의 원문을 그대로 포함한 정황은 확인하지 못했습니다.
다만 팀원이 외부 예제를 바탕으로 수정한 코드가 있다면 개발완료보고서에 원본 URL,
원 라이선스, 수정한 파일과 변경 내용을 추가해야 합니다.

## 프로젝트 자체 라이선스

현재 저장소에는 Team TRIANGLE 코드에 적용할 `LICENSE`가 없습니다. 대회 규정상
수상작 소스가 공개될 수 있으므로, 팀과 권리자가 공개 조건을 결정한 뒤에만 적절한
라이선스를 추가하세요. 이 정리 작업에서는 임의의 라이선스를 선택하지 않았습니다.

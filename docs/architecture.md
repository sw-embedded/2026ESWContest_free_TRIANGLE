# 시스템 아키텍처

## 실행 진입점

최종 진입점은 저장소 루트에서 실행하는 `python3 src/main.py`입니다.

## 실제 데이터 흐름

1. `camera.capture.CameraManager`
   - Picamera2로 기본 640×480 `RGB888` 배열을 가져옵니다.
2. `pose.detector.PoseDetector`
   - 프레임을 종횡비 보존 resize 후 정사각형 검은색 padding으로 채웁니다.
   - 설정된 MoveNet TFLite 모델을 실행합니다.
   - 출력 `[1, 1, 17, 3]`에서 17개 `(y, x, score)` keypoint를 꺼냅니다.
3. `posture.evaluator.PostureEvaluator`
   - 좌우 중 귀·어깨·골반 confidence 합이 높은 측면을 고릅니다.
   - 모델 좌표를 원본 프레임 좌표로 되돌려 목/몸통 2D 각도를 계산합니다.
   - 각도 값에 EMA(`alpha=0.3`)를 적용합니다.
   - 기본 임계값 목 22°, 몸통 15°로 자세를 판정합니다.
4. `posture.hold_timer.BadPostureHoldTimer`
   - 같은 불량 자세가 기본 60초 연속 유지될 때 교정을 한 번 요청합니다.
5. `posture.command_coordinator.PostureCommandCoordinator`
   - 자세 판정과 Arduino 교정 상태를 `C`, `N`, `R` 명령으로 연결합니다.
   - 교정 완료 상태에서 정상 자세가 기본 300초 연속 유지되면 복귀를 요청합니다.
   - 적용/복귀 구동 중에는 `N`을 보내지 않고, 남은 복귀 대기 시간을 상태에 기록합니다.
6. `actuator.serial_controller.SerialController`
   - `/dev/ttyACM0`, 9600 baud가 기본입니다.
   - 단일 worker가 시리얼 포트를 소유하고 2초마다 `H`, 1초마다 `STATUS`를 보냅니다.
   - 모든 명령은 UTF-8/ASCII와 LF 종료를 사용합니다.
7. Arduino firmware
   - 명령을 파싱하고 한 번에 한 축만 구동합니다.
   - 3초 명령 Watchdog과 D12 Active-LOW 비상정지 입력을 감시합니다.
   - 완료/오류/상태를 줄 단위 텍스트로 반환합니다.
8. `monitor.status.PoseController` + `ui.server`
   - 자세 상태와 Arduino 상태를 합쳐 `/api/status` JSON으로 제공합니다.
   - 브라우저는 1초마다 REST API를 폴링합니다.

## 구현되지 않은 발표자료 항목

- WebSocket
- MJPEG 카메라 영상 스트리밍과 골격 overlay
- TFLite 입력 버퍼로의 Zero-Copy 직접 매핑
- 이전 프레임 keypoint에 기반한 dynamic crop
- 데이터베이스/시계열 저장

위 기능은 PPT에 표현되어 있으나 현재 저장소 코드에서는 확인되지 않습니다.

## 포트 소유 구조

최종 진입점에서는 `SerialController` 인스턴스를 하나만 만들고, 자세 coordinator와
상태 controller가 같은 인스턴스를 공유합니다. Flask 서버는 시리얼 포트를 직접
열지 않으므로 최종 실행 흐름에서 포트 중복 점유는 없습니다.
`ui.main_controller.SystemController`는 이전 호출부용 어댑터이며 `src/main.py`에서
사용하지 않습니다. 별도 프로세스로 동시에 실행하면 포트 충돌이 날 수 있습니다.

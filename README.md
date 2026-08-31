# 🪑 Smart Posture Desk (스마트 자세 교정 책상)

본 프로젝트는 Picamera2와 MoveNet 딥러닝 모델을 활용하여 사용자의 거북목 및 굽은 허리 자세를 실시간 감지하고, 라즈베리파이와 아두이노(V5 프로토콜) 간 시리얼 통신을 통해 책상 높이 및 상판 기울기를 자동 제어하는 임베디드 시스템이다.

## 🛠 핵심 기능
- **실시간 자세 추정**: MoveNet TFLite 모델 및 지수 평활 필터(Exponential Filter) 기반 각도 측정
- **안전 책상 제어**: 과부하 전류 감지, 비상정지 스위치, Soft Start/Stop 제어
- **웹 모니터링**: 웹 UI를 통한 실시간 자세 및 각도 모니터링

## 🚀 실행 방법
```bash
pip install -r requirements/raspberrypi.txt
python src/main.py
---

 📁 2. 문서 파트 (`docs/`)

 📄 `docs/architecture.md`
```markdown
 🏗️ 시스템 아키텍처 및 소프트웨어 설계

 1. 시스템 구조
본 프로젝트는 라즈베리파이(Vision 및 메인 제어)와 아두이노 Uno R3(모터 및 안전 센서 제어)가 시리얼 통신으로 연결된 하이브리드 임베디드 시스템입니다.

- Vision / Main: Picamera2 + MoveNet TFLite (자세 추정 및 각도 판정)
- Monitoring: Web Server 기반 실시간 상태 모니터링
- Actuator / Safety: A4988(상판 기울기 축), L298N(책상 높이 축), 과부하 전류 센서 및 리밋 스위치

## 2. 소프트웨어 파이프라인
1. `CameraManager`: 카메라 영상 프레임 실시간 캡처 (640x480, RGB888)
2. `PoseDetector`: MoveNet TFLite 모델 추론 및 관절 Keypoint 추출
3. `PostureEvaluator`: 지수 평활 필터 적용 후 목/허리 경사각 계산 및 상태 판정 (`TURTLE_NECK`, `BENT_BACK`, `NORMAL`)
4. `SerialController`: 아두이노 제어 프로토콜(`C TURTLE_NECK`, `C BENT_BACK`, `N`, `H`) 시리얼 전송
5. `Arduino Firmware`: 비상정지 스위치, 과부하 전류 감지 등 안전 알고리즘 및 모터 구동

# smart-posture-desk
Raspberry Pi and MediaPipe-based smart posture correction desk prototype

# Smart Posture Desk

MediaPipe Pose와 Raspberry Pi를 활용한 스마트 자세 교정 책상 프로토타입입니다.

## 주요 기능

1. 카메라에서 측면 이미지 촬영
2. MediaPipe Pose 랜드마크 추출
3. 귀, 코, 눈, 어깨, 골반, 무릎 좌표 분석
4. 전방 숙임 자세 판정
5. 나쁜 자세 지속 시간 측정
6. 5분 이상 지속 시 경고
7. 책상 높이 또는 기울기 조절

## 팀 역할

### Software
- 카메라 입력
- MediaPipe 좌표 추출
- 자세 판정 알고리즘
- 지속 시간 및 경고 상태 관리

### Hardware
- 모터 및 모터 드라이버
- GPIO 제어
- 리미트 스위치
- 책상 구동 및 안전장치

## 실행 환경

- Raspberry Pi 2
- Python
- OpenCV
- MediaPipe Pose

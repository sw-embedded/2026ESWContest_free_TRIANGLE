# 🔌 하드웨어 구성 및 핀 배치표

## 1. 아두이노 Uno R3 핀 맵 (Pin Map)

| 핀 번호 | 구분 | 연결 장치 / 기능 | 비고 |
| :--- | :--- | :--- | :--- |
| **D2** | Digital OUT | A4988 STEP Pin | 스텝모터 펄스 신호 |
| **D3** | Digital OUT | A4988 DIR Pin | 스텝모터 방향 설정 |
| **D4** | Digital OUT | A4988 ENABLE Pin | LOW 활성화 |
| **D5** | Digital OUT (PWM) | L298N ENA Pin | 액추에이터 PWM 속도 제어 |
| **D6** | Digital OUT | L298N IN1 Pin | 액추에이터 방향 제어 1 |
| **D7** | Digital OUT | L298N IN2 Pin | 액추에이터 방향 제어 2 |
| **D8** | Digital IN (PULLUP) | Tilt Bottom Limit Switch | 상판 하한 리밋 |
| **D9** | Digital IN (PULLUP) | Tilt Top Limit Switch | 상판 상한 리밋 |
| **D10** | Digital IN (PULLUP) | Height Top Limit Switch | 높이 상한 리밋 |
| **D11** | Digital IN (PULLUP) | Height Bottom Limit Switch | 높이 하한 리밋 |
| **D12** | Digital IN (PULLUP) | Emergency Stop Switch | Active-LOW 비상정지 |
| **A0** | Analog IN | Current Sensor | 손끼임/과부하 감지 센서 |

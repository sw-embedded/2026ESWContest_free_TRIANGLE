# 🔌 하드웨어 구성 및 핀 배치표

## 1. 아두이노 Uno R3 핀 맵 (Pin Map)

| 핀 번호 | 구분 | 연결 장치 / 기능 | 비고 |
| :--- | :--- | :--- | :--- |
| **D2** | Digital OUT | A4988 DIR Pin | 스텝모터 방향 설정 |
| **D3** | Digital OUT | A4988 STEP Pin | 스텝모터 펄스 신호 |
| **D4~D6** | 미사용 | - | A4988 ENABLE은 LOW 활성 상태 유지, L298N ENA 점퍼 장착 |
| **D7** | Digital OUT | L298N IN1 Pin | 액추에이터 방향 제어 1 |
| **D8** | Digital OUT | L298N IN2 Pin | 액추에이터 방향 제어 2 |
| **D9~D11** | 미사용 | - | 현재 펌웨어에서 리미트 스위치 비활성화 |
| **D12** | Digital IN (PULLUP) | Emergency Stop Switch | Active-LOW 비상정지 |
| **A0** | Analog IN | Current Sensor | 손끼임/과부하 감지 센서 |

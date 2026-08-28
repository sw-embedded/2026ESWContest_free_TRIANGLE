import serial
import time
import threading

class SerialController:
    """아두이노(V5_NWCHR 프로토콜)와 통신하는 시리얼 제어 클래스"""
    def __init__(self, port='/dev/ttyACM0', baudrate=9600, enabled=True):
        self.enabled = enabled
        self.ser = None
        self.lock = threading.Lock()
        
        if self.enabled:
            try:
                self.ser = serial.Serial(port, baudrate, timeout=1)
                time.sleep(2)  # 아두이노 리셋 대기
                print("[SerialController] 아두이노 연결 완료.")
            except Exception as e:
                print(f"[SerialController] 아두이노 연결 실패: {e}")

    def send_raw(self, command: str):
        if not self.enabled or not self.ser or not self.ser.is_open:
            return
        with self.lock:
            try:
                msg = f"{command}\n".encode('utf-8')
                self.ser.write(msg)
            except Exception as e:
                print(f"[SerialController] 송신 에러: {e}")

    def send_heartbeat(self):
        """아두이노 Watchdog 해제를 위한 Heartbeat 전송"""
        self.send_raw("H")

    def send_warning(self):
        """경고 단계: 모터 정지 및 경고 상태 전달"""
        self.send_raw("W")

    def send_critical(self, posture_type: str):
        """자세 교정 동작 명령 전송 (TURTLE_NECK 또는 BENT_BACK)"""
        self.send_raw(f"C {posture_type}")

    def send_restore(self):
        """교정 후 원위치 복귀 명령 전송"""
        self.send_raw("R")

    def send_normal(self):
        """정상 자세: 동작 정지"""
        self.send_raw("N")

    def close(self):
        if self.ser and self.ser.is_open:
            self.send_normal()
            self.ser.close()

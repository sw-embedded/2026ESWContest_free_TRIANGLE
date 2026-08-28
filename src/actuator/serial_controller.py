import serial
import time
import threading

class SerialController:
    def __init__(self, port='/dev/ttyACM0', baudrate=9600, enabled=True):
        self.enabled = enabled
        self.ser = None
        self.lock = threading.Lock()
        
        if self.enabled:
            try:
                self.ser = serial.Serial(port, baudrate, timeout=1)
                time.sleep(2)
            except Exception as e:
                print(f"[SerialController] 연결 실패: {e}")

    def send_raw(self, command: str):
        if not self.enabled or not self.ser or not self.ser.is_open:
            return
        with self.lock:
            try:
                msg = f"{command}\n".encode('utf-8')
                self.ser.write(msg)
            except Exception as e:
                print(f"[SerialController] 전송 에러: {e}")

    def send_heartbeat(self):
        self.send_raw("H")

    def send_critical(self, posture_type: str):
        self.send_raw(f"C {posture_type}")

    def send_normal(self):
        self.send_raw("N")

    def close(self):
        if self.ser and self.ser.is_open:
            self.send_normal()
            self.ser.close()

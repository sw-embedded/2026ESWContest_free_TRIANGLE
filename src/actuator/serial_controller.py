import time
import threading

from actuator.arduino_state import ArduinoState

try:
    import serial
except ImportError:
    serial = None


class SerialController:
    def __init__(
        self,
        port='/dev/ttyACM0',
        baudrate=9600,
        enabled=True,
        serial_factory=None,
        startup_delay_sec=2.0,
        start_reader=True,
    ):
        self.enabled = enabled
        self.ser = None
        self.write_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.reader_thread = None
        self.state = ArduinoState()

        if self.enabled:
            try:
                if serial_factory is None:
                    if serial is None:
                        raise RuntimeError("pyserial is not installed")
                    serial_factory = serial.Serial

                self.ser = serial_factory(port, baudrate, timeout=0.2)
                time.sleep(startup_delay_sec)
                self.state.set_connected(True)
                if start_reader:
                    self.reader_thread = threading.Thread(
                        target=self._read_responses,
                        daemon=True,
                        name="arduino-serial-reader",
                    )
                    self.reader_thread.start()
            except Exception as e:
                self.state.set_connected(False, e)
                print(f"[SerialController] 연결 실패: {e}")

    def send_raw(self, command: str):
        if not self.enabled or not self.ser or not self.ser.is_open:
            self.state.set_connected(False)
            return False
        with self.write_lock:
            try:
                msg = f"{command}\n".encode('utf-8')
                self.ser.write(msg)
                return True
            except Exception as e:
                self.state.set_connected(False, e)
                print(f"[SerialController] 전송 에러: {e}")
                return False

    def _read_responses(self):
        while not self.stop_event.is_set():
            try:
                self._read_response_once()
            except Exception as e:
                if not self.stop_event.is_set():
                    self.state.set_connected(False, e)
                    print(f"[SerialController] 수신 에러: {e}")
                return

    def _read_response_once(self):
        raw_line = self.ser.readline()
        if not raw_line:
            return False
        line = raw_line.decode('utf-8', errors='replace').strip()
        if not line:
            return False
        self.state.handle_line(line)
        return True

    def send_heartbeat(self):
        return self.send_raw("H")

    def send_status(self):
        return self.send_raw("STATUS")

    def send_critical(self, posture_type: str):
        sent = self.send_raw(f"C {posture_type}")
        if sent:
            self.state.record_correction_requested(posture_type)
        return sent

    def send_normal(self):
        return self.send_raw("N")

    def send_restore(self):
        sent = self.send_raw("R")
        if sent:
            self.state.record_restore_requested()
        return sent

    def get_status(self):
        return self.state.snapshot()

    def close(self):
        if self.ser and self.ser.is_open:
            self.send_normal()
            self.stop_event.set()
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=0.5)
            self.ser.close()
        self.state.set_connected(False)

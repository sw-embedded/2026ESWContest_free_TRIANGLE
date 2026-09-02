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
        heartbeat_interval_sec=2.0,
        status_interval_sec=1.0,
        response_timeout_sec=6.0,
        reconnect_interval_sec=2.0,
        clock=time.monotonic,
    ):
        self.enabled = enabled
        self.port = port
        self.baudrate = baudrate
        self.serial_factory = serial_factory
        self.startup_delay_sec = float(startup_delay_sec)
        self.heartbeat_interval_sec = float(heartbeat_interval_sec)
        self.status_interval_sec = float(status_interval_sec)
        self.response_timeout_sec = float(response_timeout_sec)
        self.reconnect_interval_sec = float(reconnect_interval_sec)
        self.clock = clock
        self.ser = None
        self.write_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.reconnect_event = threading.Event()
        self.reader_thread = None
        self.state = ArduinoState()
        self._connected_at = None
        self._last_response_at = None
        self._next_heartbeat_at = 0.0
        self._next_status_at = 0.0

        if self.enabled:
            self._connect()
            if start_reader:
                self.reader_thread = threading.Thread(
                    target=self._run_serial_worker,
                    daemon=True,
                    name="arduino-serial-worker",
                )
                self.reader_thread.start()

    def _resolve_serial_factory(self):
        if self.serial_factory is not None:
            return self.serial_factory
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        return serial.Serial

    def _connect(self):
        if self.ser is not None and getattr(self.ser, "is_open", False):
            return True

        try:
            factory = self._resolve_serial_factory()
            new_serial = factory(self.port, self.baudrate, timeout=0.2)
            if self.stop_event.wait(self.startup_delay_sec):
                if getattr(new_serial, "is_open", False):
                    new_serial.close()
                return False

            with self.write_lock:
                self.ser = new_serial
            now = self.clock()
            self._connected_at = now
            self._last_response_at = None
            self._next_heartbeat_at = now
            self._next_status_at = now
            self.reconnect_event.clear()
            return True
        except Exception as e:
            self.ser = None
            self.state.set_connected(False, e)
            print(f"[SerialController] 연결 실패: {e}")
            return False

    def _disconnect(self, error=""):
        with self.write_lock:
            current = self.ser
            self.ser = None
        self._connected_at = None
        self._last_response_at = None
        self.reconnect_event.clear()
        self.state.set_connected(False, error)
        if current is not None and getattr(current, "is_open", False):
            try:
                current.close()
            except Exception:
                pass

    def send_raw(self, command: str):
        if not self.enabled:
            return False
        with self.write_lock:
            current = self.ser
            if not current or not getattr(current, "is_open", False):
                self.state.set_connected(False)
                self.reconnect_event.set()
                return False
            try:
                msg = f"{command}\n".encode('utf-8')
                current.write(msg)
                return True
            except Exception as e:
                self.state.set_connected(False, e)
                self.reconnect_event.set()
                print(f"[SerialController] 전송 에러: {e}")
                return False

    def _run_serial_worker(self):
        while not self.stop_event.is_set():
            if self.reconnect_event.is_set():
                self._disconnect()

            if not self.ser or not getattr(self.ser, "is_open", False):
                if not self._connect():
                    self.stop_event.wait(self.reconnect_interval_sec)
                    continue

            try:
                self._read_response_once()
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"[SerialController] 수신 에러: {e}")
                self._disconnect(e)
                self.stop_event.wait(self.reconnect_interval_sec)
                continue

            now = self.clock()
            if now >= self._next_heartbeat_at:
                self.send_heartbeat()
                self._next_heartbeat_at = now + self.heartbeat_interval_sec
            if now >= self._next_status_at:
                self.send_status()
                self._next_status_at = now + self.status_interval_sec
            self.refresh_connection_status(now)

    def _read_response_once(self):
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return False
        raw_line = self.ser.readline()
        if not raw_line:
            return False
        line = raw_line.decode('utf-8', errors='replace').strip()
        if not line:
            return False
        self._last_response_at = self.clock()
        self.state.handle_line(line)
        return True

    def refresh_connection_status(self, now=None):
        now = self.clock() if now is None else now
        response_reference = self._last_response_at
        if response_reference is None:
            response_reference = self._connected_at
        if (
            response_reference is not None
            and now - response_reference > self.response_timeout_sec
        ):
            self.state.set_connected(
                False,
                f"Arduino 응답이 {self.response_timeout_sec:g}초 동안 없습니다",
            )
            self.reconnect_event.set()

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
        self.refresh_connection_status()
        status = self.state.snapshot()
        status["serial_port"] = self.port
        if self._last_response_at is None:
            status["arduino_response_age_sec"] = None
        else:
            status["arduino_response_age_sec"] = round(
                max(0.0, self.clock() - self._last_response_at), 1
            )
        return status

    def close(self):
        if self.ser and getattr(self.ser, "is_open", False):
            self.send_normal()
        self.stop_event.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1.0)
        self._disconnect()

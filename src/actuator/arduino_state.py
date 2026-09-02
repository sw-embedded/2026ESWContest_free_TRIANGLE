import threading


class ArduinoState:
    """Arduino 응답에서 웹 UI와 제어 로직에 필요한 상태를 추적한다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {
            "arduino_connected": False,
            "correction_phase": "IDLE",
            "active_correction": "NONE",
            "restore_remaining_sec": None,
            "emergency_stop": False,
            "current_sensor": None,
            "tilt_mm": None,
            "tilt_mode": None,
            "height_mode": None,
            "last_arduino_response": "",
            "last_arduino_error": "",
            "serial_error": "",
            "watchdog_timeout_sec": None,
        }

    def snapshot(self):
        with self._lock:
            return dict(self._status)

    def set_connected(self, connected, error=""):
        with self._lock:
            self._status["arduino_connected"] = bool(connected)
            if error:
                self._status["serial_error"] = str(error)
            elif connected:
                self._status["serial_error"] = ""

    def record_correction_requested(self, posture_type):
        with self._lock:
            self._status["correction_phase"] = "APPLYING"
            self._status["active_correction"] = posture_type
            self._status["last_arduino_error"] = ""

    def record_restore_requested(self):
        with self._lock:
            self._status["correction_phase"] = "RESTORING"
            self._status["last_arduino_error"] = ""

    def handle_line(self, line):
        line = line.strip()
        if not line:
            return

        with self._lock:
            self._status["arduino_connected"] = True
            self._status["serial_error"] = ""
            self._status["last_arduino_response"] = line

            if line.startswith("READY "):
                self._status["correction_phase"] = "IDLE"
                self._status["active_correction"] = "NONE"
                self._status["last_arduino_error"] = ""
            elif line.startswith("OK CORRECTION_"):
                self._status["correction_phase"] = "APPLYING"
                self._status["active_correction"] = line.removeprefix(
                    "OK CORRECTION_"
                )
            elif line.startswith("DONE CORRECTION "):
                self._status["correction_phase"] = "APPLIED"
                self._status["active_correction"] = line.removeprefix(
                    "DONE CORRECTION "
                )
            elif line == "DONE RESTORE":
                self._status["correction_phase"] = "IDLE"
                self._status["active_correction"] = "NONE"
            elif line.startswith("ERR "):
                self._status["last_arduino_error"] = line
                if (
                    self._status["correction_phase"]
                    in ("APPLYING", "RESTORING")
                    or self._is_motion_fault(line)
                ):
                    self._status["correction_phase"] = "FAULT"
            elif line.startswith("STATUS "):
                self._apply_status_line(line)

    def _apply_status_line(self, line):
        values = {}
        for token in line.split()[1:]:
            if "=" in token:
                key, value = token.split("=", 1)
                values[key] = value

        phase = values.get("CORRECTION_PHASE")
        correction_type = values.get("CORRECTION_TYPE")
        if phase:
            self._status["correction_phase"] = phase
        if correction_type:
            self._status["active_correction"] = correction_type

        self._set_number(values, "CURRENT", "current_sensor", int)
        self._set_number(values, "TILT_MM", "tilt_mm", float)
        self._set_number(values, "TILT_MODE", "tilt_mode", int)
        self._set_number(values, "HEIGHT_MODE", "height_mode", int)

        if "WATCHDOG_MS" in values:
            try:
                self._status["watchdog_timeout_sec"] = (
                    int(values["WATCHDOG_MS"]) / 1000.0
                )
            except ValueError:
                pass

        if "ESTOP" in values:
            self._status["emergency_stop"] = values["ESTOP"] == "1"

    def _set_number(self, values, source_key, target_key, converter):
        if source_key not in values:
            return
        try:
            self._status[target_key] = converter(values[source_key])
        except ValueError:
            pass

    def _is_motion_fault(self, line):
        fault_markers = (
            "CORRECTION_FAULT",
            "EMERGENCY_STOP",
            "OVERCURRENT",
            "WATCHDOG",
            "TILT_TIMEOUT",
            "RESTORE_NOT_STARTED",
        )
        return any(marker in line for marker in fault_markers)

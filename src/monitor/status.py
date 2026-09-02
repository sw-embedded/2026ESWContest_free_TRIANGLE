import threading


class PoseController:
    """카메라 상태와 최신 Arduino 상태를 하나의 웹 스냅샷으로 합친다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._serial_controller = None
        self._vision_status = {
            "pose": "INIT",
            "neck_angle": 0.0,
            "back_angle": 0.0,
            "correction_phase": "IDLE",
            "active_correction": "NONE",
            "restore_remaining_sec": None,
            "arduino_connected": False,
            "emergency_stop": False,
            "current_sensor": None,
            "tilt_mm": None,
            "last_arduino_response": "",
            "last_arduino_error": "",
            "serial_error": "",
            "serial_port": "",
            "arduino_response_age_sec": None,
            "watchdog_timeout_sec": None,
            "updated_time": "-",
        }

    def attach_serial_controller(self, serial_controller):
        self._serial_controller = serial_controller

    def update_pose(self, pose, neck_angle, back_angle, updated_time):
        with self._lock:
            self._vision_status.update({
                "pose": pose,
                "neck_angle": neck_angle,
                "back_angle": back_angle,
                "updated_time": updated_time,
            })

    def get_status(self):
        with self._lock:
            status = dict(self._vision_status)
        if self._serial_controller is not None:
            status.update(self._serial_controller.get_status())
        return status

    @property
    def current_status(self):
        """이전 호출부와 웹 서버를 위한 최신 통합 상태 스냅샷."""
        return self.get_status()

import time


class PostureCommandCoordinator:
    """자세 전환과 Arduino 교정 상태를 명령으로 연결한다."""

    def __init__(
        self,
        serial_controller,
        normal_restore_delay_sec=300,
        clock=time.monotonic,
    ):
        normal_restore_delay_sec = float(normal_restore_delay_sec)
        if normal_restore_delay_sec < 0:
            raise ValueError("normal_restore_delay_sec must be non-negative")

        self.serial_controller = serial_controller
        self.normal_restore_delay_sec = normal_restore_delay_sec
        self._clock = clock
        self._previous_pose = None
        self._restore_requested = False
        self._normal_started_at = None
        self._pending_critical = None
        self._normal_pending = False

    def update(self, pose, critical_posture=None):
        if critical_posture is not None:
            self._pending_critical = critical_posture

        if self._pending_critical is not None:
            if pose != self._pending_critical:
                self._pending_critical = None
            elif self.serial_controller.send_critical(self._pending_critical):
                self._pending_critical = None

        if pose == "NORMAL" and self._previous_pose != "NORMAL":
            self._normal_pending = True
        elif pose != "NORMAL":
            self._normal_pending = False

        arduino_status = self.serial_controller.get_status()
        correction_phase = arduino_status["correction_phase"]

        # 교정/복귀 모터가 움직이는 동안 N을 보내면 Arduino가 안전상 FAULT로
        # 전환하므로, 정지 상태(IDLE/APPLIED)에서만 NORMAL을 전달한다.
        if (
            self._normal_pending
            and correction_phase in ("IDLE", "APPLIED")
            and self.serial_controller.send_normal()
        ):
            self._normal_pending = False

        if correction_phase in ("IDLE", "FAULT"):
            self._restore_requested = False
            self._normal_started_at = None

        if pose == "NORMAL" and correction_phase == "APPLIED":
            now = self._clock()
            if self._normal_started_at is None:
                self._normal_started_at = now

            normal_duration_sec = now - self._normal_started_at
            if (
                normal_duration_sec >= self.normal_restore_delay_sec
                and not self._restore_requested
            ):
                self._restore_requested = self.serial_controller.send_restore()
        else:
            self._normal_started_at = None

        self._previous_pose = pose

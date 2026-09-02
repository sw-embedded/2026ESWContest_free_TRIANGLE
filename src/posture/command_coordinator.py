class PostureCommandCoordinator:
    """자세 전환과 Arduino 교정 상태를 명령으로 연결한다."""

    def __init__(self, serial_controller):
        self.serial_controller = serial_controller
        self._previous_pose = None
        self._restore_requested = False
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
        if self._normal_pending and self.serial_controller.send_normal():
            self._normal_pending = False

        arduino_status = self.serial_controller.get_status()
        correction_phase = arduino_status["correction_phase"]
        if correction_phase in ("IDLE", "FAULT"):
            self._restore_requested = False

        if (
            pose == "NORMAL"
            and correction_phase == "APPLIED"
            and not self._restore_requested
        ):
            self._restore_requested = self.serial_controller.send_restore()

        self._previous_pose = pose

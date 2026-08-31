import time


BAD_POSTURES = frozenset({"TURTLE_NECK", "BENT_BACK"})


class BadPostureHoldTimer:
    """같은 잘못된 자세가 지정 시간 동안 연속된 경우 한 번만 알린다."""

    def __init__(self, hold_duration_sec, clock=time.monotonic):
        self.hold_duration_sec = float(hold_duration_sec)
        if self.hold_duration_sec < 0:
            raise ValueError("hold_duration_sec must be non-negative")

        self._clock = clock
        self._candidate_pose = None
        self._started_at = None
        self._triggered = False

    def reset(self):
        self._candidate_pose = None
        self._started_at = None
        self._triggered = False

    def update(self, pose, now=None):
        """구동해야 할 자세를 반환하며, 아직 조건 미충족이면 None을 반환한다."""
        current_time = self._clock() if now is None else now

        if pose not in BAD_POSTURES:
            self.reset()
            return None

        if pose != self._candidate_pose:
            self._candidate_pose = pose
            self._started_at = current_time
            self._triggered = False

        if (
            not self._triggered
            and current_time - self._started_at >= self.hold_duration_sec
        ):
            self._triggered = True
            return pose

        return None

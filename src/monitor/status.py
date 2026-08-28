# src/monitor/status.py 내용 예시
class PoseController:
    """실시간 자세 및 모니터링 상태 관리 클래스"""
    def __init__(self):
        self.current_status = {
            "pose": "INIT",
            "neck_angle": 0.0,
            "back_angle": 0.0,
            "updated_time": "-"
        }

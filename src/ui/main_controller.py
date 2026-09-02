import time


from actuator.serial_controller import SerialController
from monitor.status import PoseController


class SystemController:
    """이전 UI 호출부를 현재 줄 단위 Arduino 프로토콜에 연결하는 어댑터."""

    def __init__(self, port='/dev/ttyACM0', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_controller = SerialController(port=port, baudrate=baudrate)
        self.status_controller = PoseController()
        self.status_controller.attach_serial_controller(self.serial_controller)
        self.last_sent_pose = None

    @property
    def current_status(self):
        return self.status_controller.get_status()

    def update_pose(self, pose_name, neck_angle, back_angle):
        """AI 결과값을 받아서 상태를 갱신하고 신호를 전달하는 메인 함수"""
        self.status_controller.update_pose(
            pose_name,
            int(neck_angle),
            int(back_angle),
            time.strftime("%H:%M:%S"),
        )

        if pose_name == self.last_sent_pose:
            return
        if pose_name == "NORMAL":
            sent = self.serial_controller.send_normal()
        elif pose_name in ("TURTLE_NECK", "BENT_BACK"):
            sent = self.serial_controller.send_critical(pose_name)
        else:
            sent = True
        if sent:
            self.last_sent_pose = pose_name

    def close(self):
        self.serial_controller.close()

import serial
import time

class SystemController:
    def __init__(self, port='/dev/ttyACM0', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        
        # 실시간 상태 저장 변수
        self.current_status = {
            "pose": "NORMAL",
            "neck_angle": 0,
            "back_angle": 0,
            "last_command": "N",
            "updated_time": ""
        }
        
        # 직전 송신 신호 (중복 전송 방지용)
        self.last_sent_command = None
        self.init_serial()

    def init_serial(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)
            print(f"[System] 아두이노 연결 성공: {self.port}")
        except Exception as e:
            self.ser = None
            print(f"[System] 아두이노 미연결 (테스트/대기 모드): {e}")

    def update_pose(self, pose_name, neck_angle, back_angle):
        """AI 결과값을 받아서 상태를 갱신하고 신호를 전달하는 메인 함수"""
        self.current_status["pose"] = pose_name
        self.current_status["neck_angle"] = int(neck_angle)
        self.current_status["back_angle"] = int(back_angle)
        self.current_status["updated_time"] = time.strftime("%H:%M:%S")

        # 신호 매핑
        target_command = 'N'
        if pose_name == "TURTLE_NECK":
            target_command = 'T'
        elif pose_name == "BENT_BACK":
            target_command = 'B'

        # 자세 상태가 변했을 때만 아두이노로 신호 1회 송신 (과부하 방지)
        if target_command != self.last_sent_command:
            self.send_to_arduino(target_command)
            self.last_sent_command = target_command
            self.current_status["last_command"] = target_command

    def send_to_arduino(self, command_char):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(command_char.encode())
                print(f"[TX -> Arduino] 신호 전송: {command_char}")
            except Exception as e:
                print(f"[Error] 전송 실패: {e}")
        else:
            print(f"[Mock TX] 신호: {command_char}")

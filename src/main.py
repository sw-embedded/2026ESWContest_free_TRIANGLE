import cv2
import mediapipe as mp
import math
import time
import serial
import threading
from datetime import datetime

# server.py 모듈 임포트
from ui.server import start_server

# ==========================================
# 1. 웹 서버에 공유할 데이터를 담는 객체
# ==========================================
class PoseController:
    def __init__(self):
        self.current_status = {
            "pose": "NORMAL",
            "neck_angle": 0,
            "back_angle": 0,
            "updated_time": "-"
        }

controller = PoseController()

# 웹 서버를 백그라운드 스레드로 실행
server_thread = threading.Thread(target=start_server, args=(controller,), daemon=True)
server_thread.start()
print("웹 모니터링 서버가 백그라운드에서 실행되었습니다. (port 5000)")

# ==========================================
# 2. 아두이노 시리얼 통신 설정
# ==========================================
try:
    ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
    time.sleep(2)
    print("아두이노 시리얼 통신 연결 성공")
except Exception as e:
    print(f"시리얼 통신 연결 실패 (가상 테스트 모드): {e}")
    ser = None

VALID_ARDUINO_COMMANDS = {"N", "W", "C", "H"}
HEARTBEAT_INTERVAL_SEC = 1.0
last_heartbeat_time = 0.0
last_posture_command = None


def send_arduino_command(cmd, log_output=True):
    """N/W/C/H 명령을 줄바꿈으로 종료해 아두이노로 전송한다."""
    if cmd not in VALID_ARDUINO_COMMANDS:
        raise ValueError(f"지원하지 않는 아두이노 명령: {cmd}")

    if ser and ser.is_open:
        try:
            ser.write(f"{cmd}\n".encode("ascii"))
            if log_output:
                print(f"[SERIAL OUT] 명령 전송: {cmd}")
            return True
        except serial.SerialException as e:
            print(f"[SERIAL ERROR] 명령 전송 실패: {e}")
    return False


def send_posture_command(cmd):
    """자세 상태가 바뀔 때만 N/W/C 명령을 전송한다."""
    global last_posture_command

    if cmd != last_posture_command and send_arduino_command(cmd):
        last_posture_command = cmd


def send_heartbeat_if_due():
    """Arduino의 3초 watchdog보다 짧은 1초 주기로 H를 전송한다."""
    global last_heartbeat_time

    now = time.monotonic()
    if now - last_heartbeat_time >= HEARTBEAT_INTERVAL_SEC:
        if send_arduino_command("H", log_output=False):
            last_heartbeat_time = now

# ==========================================
# 3. MediaPipe Pose 및 기본 변수 설정
# ==========================================
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=0,
    smooth_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def calculate_vertical_angle(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    angle_rad = math.atan2(abs(dx), abs(dy))
    return round(math.degrees(angle_rad), 1)

# 지속 시간 측정 변수 (5분 = 300초)
BAD_POSTURE_THRESHOLD_SEC = 300
bad_posture_start_time = None

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

print("=== 라즈베리파이 AI 자세 감지 및 웹 모니터링 시작 ===")
send_posture_command("N")

while cap.isOpened():
    send_heartbeat_if_due()

    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    results = pose.process(rgb_frame)
    
    current_status = "NORMAL"
    status_color = (0, 255, 0)
    neck_angle = 0.0
    back_angle = 0.0

    if results.pose_landmarks:
        landmarks = results.pose_landmarks.landmark
        
        # 6개 주요 좌표 추출 (오른쪽 측면)
        ear = (int(landmarks[mp_pose.PoseLandmark.RIGHT_EAR].x * w),
               int(landmarks[mp_pose.PoseLandmark.RIGHT_EAR].y * h))
        shoulder = (int(landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER].x * w),
                    int(landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER].y * h))
        hip = (int(landmarks[mp_pose.PoseLandmark.RIGHT_HIP].x * w),
               int(landmarks[mp_pose.PoseLandmark.RIGHT_HIP].y * h))

        # 각도 계산
        neck_angle = calculate_vertical_angle(ear, shoulder)
        back_angle = calculate_vertical_angle(shoulder, hip)
        
        # 자세 판단
        if neck_angle > 15:
            current_status = "TURTLE_NECK"
            status_color = (0, 0, 255)
        elif back_angle > 20:
            current_status = "BENT_BACK"
            status_color = (0, 165, 255)

        # ------------------------------------------
        # 4. 팀원의 server.py로 실시간 데이터 송출
        # ------------------------------------------
        controller.current_status = {
            "pose": current_status,
            "neck_angle": neck_angle,
            "back_angle": back_angle,
            "updated_time": datetime.now().strftime("%H:%M:%S")
        }

        # 나쁜 자세 5분 타이머 및 시리얼 전송
        if current_status in ["TURTLE_NECK", "BENT_BACK"]:
            if bad_posture_start_time is None:
                bad_posture_start_time = time.monotonic()

            elapsed_time = int(time.monotonic() - bad_posture_start_time)

            if elapsed_time >= BAD_POSTURE_THRESHOLD_SEC:
                send_posture_command("C")  # Critical: 자동 기울기 보정
            else:
                send_posture_command("W")  # Warning: 모터 정지 유지
        else:
            bad_posture_start_time = None
            send_posture_command("N")  # Normal: 모든 모터 정지
    else:
        bad_posture_start_time = None
        controller.current_status = {
            "pose": "POSE_LOST",
            "neck_angle": 0.0,
            "back_angle": 0.0,
            "updated_time": datetime.now().strftime("%H:%M:%S")
        }
        send_posture_command("N")

    # 화면에 텍스트 표시
    cv2.putText(frame, f"STATUS: {current_status}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

    cv2.imshow("Raspberry Pi AI Posture Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if ser and ser.is_open:
    send_arduino_command("N")
    ser.close()
cv2.destroyAllWindows()

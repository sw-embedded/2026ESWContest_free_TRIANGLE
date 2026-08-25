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
            "correction_phase": "IDLE",
            "active_correction": "NONE",
            "restore_remaining_sec": None,
            "arduino_connected": False,
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

VALID_ARDUINO_COMMANDS = {
    "N",
    "W",
    "C TURTLE_NECK",
    "C BENT_BACK",
    "H",
    "R",
    "STATUS",
}
HEARTBEAT_INTERVAL_SEC = 1.0
NORMAL_RESTORE_THRESHOLD_SEC = 300

CORRECTION_IDLE = "IDLE"
CORRECTION_APPLYING = "APPLYING"
CORRECTION_APPLIED = "APPLIED"
CORRECTION_RESTORING = "RESTORING"
CORRECTION_FAULT = "FAULT"

last_heartbeat_time = 0.0
last_posture_command = None
correction_phase = CORRECTION_IDLE
active_correction = None
normal_posture_start_time = None


def update_web_correction_status():
    """현재 교정·복귀 상태를 웹 API에 함께 공개한다."""
    restore_remaining_sec = None
    if (correction_phase == CORRECTION_APPLIED and
            normal_posture_start_time is not None):
        normal_elapsed = time.monotonic() - normal_posture_start_time
        restore_remaining_sec = max(
            0,
            math.ceil(NORMAL_RESTORE_THRESHOLD_SEC - normal_elapsed)
        )

    controller.current_status.update({
        "correction_phase": correction_phase,
        "active_correction": active_correction or "NONE",
        "restore_remaining_sec": restore_remaining_sec,
        "arduino_connected": bool(ser and ser.is_open),
    })


def send_arduino_command(cmd, log_output=True):
    """검증된 명령을 줄바꿈으로 종료해 아두이노로 전송한다."""
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
    """교정 전의 N/W 상태가 바뀔 때만 명령을 전송한다."""
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


def update_correction_state_from_status(message):
    """STATUS 응답으로 재실행 후에도 Arduino의 교정 잠금 상태를 복구한다."""
    global correction_phase, active_correction

    values = {}
    for token in message.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            values[key] = value

    phase = values.get("CORRECTION_PHASE")
    correction_type = values.get("CORRECTION_TYPE")
    if phase in {
        CORRECTION_IDLE,
        CORRECTION_APPLYING,
        CORRECTION_APPLIED,
        CORRECTION_RESTORING,
        CORRECTION_FAULT,
    }:
        correction_phase = phase
        active_correction = None if correction_type == "NONE" else correction_type


def handle_arduino_message(message):
    """Arduino 완료·오류 응답을 교정 잠금 상태에 반영한다."""
    global correction_phase, active_correction
    global normal_posture_start_time, bad_posture_start_time
    global bad_posture_type, last_posture_command

    if message.startswith("STATUS "):
        update_correction_state_from_status(message)
    elif message.startswith("DONE CORRECTION "):
        correction_phase = CORRECTION_APPLIED
        active_correction = message.removeprefix("DONE CORRECTION ")
        normal_posture_start_time = None
    elif message == "DONE RESTORE":
        correction_phase = CORRECTION_IDLE
        active_correction = None
        normal_posture_start_time = None
        bad_posture_start_time = None
        bad_posture_type = None
        last_posture_command = None
    elif message.startswith("ERR CORRECTION_FAULT"):
        correction_phase = CORRECTION_FAULT
        normal_posture_start_time = None
    elif message in {"ERR CORRECTION_NOT_STARTED", "ERR RESTORE_NOT_STARTED"}:
        # 자동 재시도로 예상하지 못한 추가 움직임이 생기지 않도록 정지 상태로 잠근다.
        correction_phase = CORRECTION_FAULT
        normal_posture_start_time = None


def read_arduino_messages():
    """대기 중인 Arduino 응답을 비차단 방식으로 모두 읽는다."""
    if not ser or not ser.is_open:
        return

    try:
        while ser.in_waiting > 0:
            message = ser.readline().decode("ascii", errors="replace").strip()
            if not message:
                continue
            if message != "PONG":
                print(f"[SERIAL IN] {message}")
            handle_arduino_message(message)
    except serial.SerialException as e:
        print(f"[SERIAL ERROR] 응답 수신 실패: {e}")

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
bad_posture_type = None

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

print("=== 라즈베리파이 AI 자세 감지 및 웹 모니터링 시작 ===")
send_posture_command("N")
send_arduino_command("STATUS")

while cap.isOpened():
    send_heartbeat_if_due()
    read_arduino_messages()

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

        # 나쁜 자세 교정, 교정 잠금, 장시간 정상 자세 후 복귀 상태 머신
        if correction_phase == CORRECTION_IDLE:
            normal_posture_start_time = None

            if current_status in ["TURTLE_NECK", "BENT_BACK"]:
                # 다른 종류의 나쁜 자세로 바뀌면 해당 자세의 5분을 다시 측정한다.
                if (bad_posture_start_time is None or
                        bad_posture_type != current_status):
                    bad_posture_start_time = time.monotonic()
                    bad_posture_type = current_status

                elapsed_time = int(time.monotonic() - bad_posture_start_time)
                if elapsed_time >= BAD_POSTURE_THRESHOLD_SEC:
                    critical_command = f"C {current_status}"
                    if send_arduino_command(critical_command):
                        correction_phase = CORRECTION_APPLYING
                        active_correction = current_status
                        last_posture_command = critical_command
                else:
                    send_posture_command("W")
            else:
                bad_posture_start_time = None
                bad_posture_type = None
                send_posture_command("N")

        elif correction_phase == CORRECTION_APPLIED:
            # 교정된 동안 다른 나쁜 자세가 보여도 C/W/N 모터 명령을 보내지 않는다.
            bad_posture_start_time = None
            bad_posture_type = None

            if current_status == "NORMAL":
                if normal_posture_start_time is None:
                    normal_posture_start_time = time.monotonic()

                normal_elapsed = time.monotonic() - normal_posture_start_time
                if normal_elapsed >= NORMAL_RESTORE_THRESHOLD_SEC:
                    if send_arduino_command("R"):
                        correction_phase = CORRECTION_RESTORING
                        normal_posture_start_time = None
            else:
                # 자세 인식 실패나 나쁜 자세가 한 번이라도 나오면 정상 타이머를 초기화한다.
                normal_posture_start_time = None

        else:
            # APPLYING/RESTORING/FAULT에서는 heartbeat 외의 동작 명령을 금지한다.
            bad_posture_start_time = None
            bad_posture_type = None
            normal_posture_start_time = None
    else:
        bad_posture_start_time = None
        bad_posture_type = None
        controller.current_status = {
            "pose": "POSE_LOST",
            "neck_angle": 0.0,
            "back_angle": 0.0,
            "updated_time": datetime.now().strftime("%H:%M:%S")
        }
        if correction_phase == CORRECTION_IDLE:
            send_posture_command("N")
        elif correction_phase == CORRECTION_APPLIED:
            normal_posture_start_time = None

    update_web_correction_status()

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

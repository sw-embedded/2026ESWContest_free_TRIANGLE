import cv2
import numpy as np
import math
import time
import serial
import threading
from datetime import datetime

# tflite-runtime 라이브러리 임포트
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    import tensorflow.lite as tflite  # PC 테스트 환경용 예외 처리

# server.py 모듈 임포트
from ui.server import start_server

# ==========================================
# 1. 웹 서버 공유 객체
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

server_thread = threading.Thread(target=start_server, args=(controller,), daemon=True)
server_thread.start()
print("웹 모니터링 서버 실행 완료 (Port 5000)")

# ==========================================
# 2. 아두이노 시리얼 통신 설정 및 변수
# ==========================================
try:
    ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
    time.sleep(2)
    print("아두이노 시리얼 통신 연결 성공")
except Exception as e:
    print(f"시리얼 통신 연결 실패 (가상 테스트 모드): {e}")
    ser = None

VALID_ARDUINO_COMMANDS = {
    "N", "W", "C TURTLE_NECK", "C BENT_BACK", "H", "R", "STATUS"
}
HEARTBEAT_INTERVAL_SEC = 1.0
NORMAL_RESTORE_THRESHOLD_SEC = 300
BAD_POSTURE_THRESHOLD_SEC = 300  # 시연 시 필요에 따라 짧게 변경 가능

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
bad_posture_start_time = None
bad_posture_type = None


def update_web_correction_status():
    restore_remaining_sec = None
    if (correction_phase == CORRECTION_APPLIED and normal_posture_start_time is not None):
        normal_elapsed = time.monotonic() - normal_posture_start_time
        restore_remaining_sec = max(0, math.ceil(NORMAL_RESTORE_THRESHOLD_SEC - normal_elapsed))

    controller.current_status.update({
        "correction_phase": correction_phase,
        "active_correction": active_correction or "NONE",
        "restore_remaining_sec": restore_remaining_sec,
        "arduino_connected": bool(ser and ser.is_open),
    })

def send_arduino_command(cmd, log_output=True):
    if cmd not in VALID_ARDUINO_COMMANDS:
        raise ValueError(f"지원하지 않는 명령: {cmd}")
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
    global last_posture_command
    if cmd != last_posture_command and send_arduino_command(cmd):
        last_posture_command = cmd

def send_heartbeat_if_due():
    global last_heartbeat_time
    now = time.monotonic()
    if now - last_heartbeat_time >= HEARTBEAT_INTERVAL_SEC:
        if send_arduino_command("H", log_output=False):
            last_heartbeat_time = now

def handle_arduino_message(message):
    global correction_phase, active_correction, normal_posture_start_time
    global bad_posture_start_time, bad_posture_type, last_posture_command

    if message.startswith("STATUS "):
        # 아두이노 STATUS 응답 동기화 로직
        pass
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
    elif message.startswith("ERR"):
        correction_phase = CORRECTION_FAULT
        normal_posture_start_time = None

def read_arduino_messages():
    if not ser or not ser.is_open:
        return
    try:
        while ser.in_waiting > 0:
            message = ser.readline().decode("ascii", errors="replace").strip()
            if message and message != "PONG":
                print(f"[SERIAL IN] {message}")
                handle_arduino_message(message)
    except serial.SerialException as e:
        print(f"[SERIAL ERROR] 수신 실패: {e}")

# ==========================================
# 3. TFLite MoveNet 모델 로드 및 전처리 함수
# ==========================================
MODEL_PATH = "models/movenet_lightning.tflite"
interpreter = tflite.Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
input_shape = input_details[0]['shape']  # [1, 192, 192, 3]

# MoveNet 주요 관절 인덱스 (오른쪽 측면)
RIGHT_EAR_IDX = 4
RIGHT_SHOULDER_IDX = 6
RIGHT_HIP_IDX = 12

def calculate_vertical_angle(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    angle_rad = math.atan2(abs(dx), abs(dy))
    return round(math.degrees(angle_rad), 1)

# ==========================================
# 4. 메인 분석 루프
# ==========================================
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

print("=== TFLite 기반 AI 자세 감지 시작 ===")
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

    # 1) TFLite 모델용 입력 전처리 (192x192 RGB)
    input_img = cv2.resize(frame, (192, 192))
    input_img = cv2.cvtColor(input_img, cv2.COLOR_BGR2RGB)
    
    # 모델의 Input Type에 맞춰 타입 변환 (int32 또는 float32)
    if input_details[0]['dtype'] == np.uint8:
        input_tensor = np.expand_dims(input_img, axis=0).astype(np.uint8)
    else:
        input_tensor = np.expand_dims(input_img, axis=0).astype(np.float32)

    # 2) TFLite 추론 실행
    interpreter.set_tensor(input_details[0]['index'], input_tensor)
    interpreter.invoke()
    keypoints = interpreter.get_tensor(output_details[0]['index'])[0][0] # Shape: [17, 3] (y, x, score)

    # 3) 주요 관절 extraction (오른쪽 귀, 어깨, 골반)
    ear_kpt = keypoints[RIGHT_EAR_IDX]
    shoulder_kpt = keypoints[RIGHT_SHOULDER_IDX]
    hip_kpt = keypoints[RIGHT_HIP_IDX]

    # Confidence Score 검증 (신뢰도 > 0.3)
    if ear_kpt[2] > 0.3 and shoulder_kpt[2] > 0.3 and hip_kpt[2] > 0.3:
        ear = (int(ear_kpt[1] * w), int(ear_kpt[0] * h))
        shoulder = (int(shoulder_kpt[1] * w), int(shoulder_kpt[0] * h))
        hip = (int(hip_kpt[1] * w), int(hip_kpt[0] * h))

        # 각도 계산
        neck_angle = calculate_vertical_angle(ear, shoulder)
        back_angle = calculate_vertical_angle(shoulder, hip)

        # 자세 판별
        current_status = "NORMAL"
        status_color = (0, 255, 0)
        if neck_angle > 15:
            current_status = "TURTLE_NECK"
            status_color = (0, 0, 255)
        elif back_angle > 20:
            current_status = "BENT_BACK"
            status_color = (0, 165, 255)

        controller.current_status.update({
            "pose": current_status,
            "neck_angle": neck_angle,
            "back_angle": back_angle,
            "updated_time": datetime.now().strftime("%H:%M:%S")
        })

        # 자세 교정 상태 머신 로직 (기존과 동일)
        if correction_phase == CORRECTION_IDLE:
            normal_posture_start_time = None
            if current_status in ["TURTLE_NECK", "BENT_BACK"]:
                if bad_posture_start_time is None or bad_posture_type != current_status:
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
            bad_posture_start_time = None
            if current_status == "NORMAL":
                if normal_posture_start_time is None:
                    normal_posture_start_time = time.monotonic()
                if time.monotonic() - normal_posture_start_time >= NORMAL_RESTORE_THRESHOLD_SEC:
                    if send_arduino_command("R"):
                        correction_phase = CORRECTION_RESTORING
                        normal_posture_start_time = None
            else:
                normal_posture_start_time = None

    else:
        # 관절 감지 실패 (POSE_LOST)
        bad_posture_start_time = None
        controller.current_status.update({
            "pose": "POSE_LOST",
            "neck_angle": 0.0,
            "back_angle": 0.0,
            "updated_time": datetime.now().strftime("%H:%M:%S")
        })
        if correction_phase == CORRECTION_IDLE:
            send_posture_command("N")

    update_web_correction_status()

    # 화면 렌더링
    cv2.putText(frame, f"STATUS: {controller.current_status['pose']}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.imshow("Raspberry Pi AI Posture Detection (TFLite)", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if ser and ser.is_open:
    send_arduino_command("N")
    ser.close()
cv2.destroyAllWindows()

import cv2
import mediapipe as mp
import math
import time
import serial

# ==========================================
# 1. 아두이노 시리얼 통신 설정 (Hardware 연동용)
# ==========================================
# 라즈베리파이 USB 포트 연결 기준 (필요 시 포트명 변경, 예: '/dev/ttyACM0')
try:
    ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
    time.sleep(2)  # 시리얼 초기화 대기
    print("아두이노 시리얼 통신 연결 성공")
except Exception as e:
    print(f"시리얼 통신 연결 실패 (가상 테스트 모드 진행): {e}")
    ser = None

def send_arduino_command(cmd):
    """아두이노로 모터 제어/경고 명령 전송 (S: 정지, A: 각도조절, H: 높이조절, W: 경고)"""
    if ser and ser.is_open:
        ser.write(f"{cmd}\n".encode('utf-8'))
        print(f"[SERIAL OUT] 아두이노 명령 전송: {cmd}")

# ==========================================
# 2. MediaPipe Pose 및 기본 변수 설정
# ==========================================
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

# Raspberry Pi 2 성능 최적화를 위한 설정 (model_complexity=0 사용)
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=0,
    smooth_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def calculate_angle(p1, p2):
    """두 점 사이의 기울기 각도(도) 계산"""
    x1, y1 = p1
    x2, y2 = p2
    angle_rad = math.atan2(abs(y2 - y1), abs(x2 - x1))
    return math.degrees(angle_rad)

# 지속 시간 측정 변수 (5분 = 300초)
BAD_POSTURE_THRESHOLD_SEC = 300  
bad_posture_start_time = None
alert_triggered = False

# 웹캠 / 라즈베리파이 카메라 연결
cap = cv2.VideoCapture(0)
# 연산 부하 감소를 위해 해상도를 320x240으로 낮춤 (라즈베리파이 2 권장)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

print("=== 라즈베리파이 자세 감지 및 구동 시스템 시작 ===")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("카메라 영상을 읽을 수 없습니다.")
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # MediaPipe 좌표 추출
    results = pose.process(rgb_frame)
    
    current_status = "NORMAL"
    status_color = (0, 255, 0) # 정상: 초록색

    if results.pose_landmarks:
        landmarks = results.pose_landmarks.landmark
        
        # ------------------------------------------
        # 깃허브 명세에 따른 6개 주요 좌표 추출 (측면 기준: 오른쪽)
        # ------------------------------------------
        ear = (int(landmarks[mp_pose.PoseLandmark.RIGHT_EAR].x * w),
               int(landmarks[mp_pose.PoseLandmark.RIGHT_EAR].y * h))
        eye = (int(landmarks[mp_pose.PoseLandmark.RIGHT_EYE].x * w),
               int(landmarks[mp_pose.PoseLandmark.RIGHT_EYE].y * h))
        nose = (int(landmarks[mp_pose.PoseLandmark.RIGHT_NOSE].x * w),
                int(landmarks[mp_pose.PoseLandmark.RIGHT_NOSE].y * h))
        shoulder = (int(landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER].x * w),
                    int(landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER].y * h))
        hip = (int(landmarks[mp_pose.PoseLandmark.RIGHT_HIP].x * w),
               int(landmarks[mp_pose.PoseLandmark.RIGHT_HIP].y * h))
        knee = (int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].x * w),
                int(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE].y * h))

        # ------------------------------------------
        # 자세 판정 알고리즘 (전방 숙임 판정)
        # ------------------------------------------
        neck_angle = calculate_angle(ear, shoulder)
        back_angle = calculate_angle(shoulder, hip)
        
        # 귀-어깨 각도 또는 어깨-골반 기울기가 기준치 미만이면 전방 숙임 자세로 판단
        if neck_angle < 45 or back_angle < 60:
            current_status = "FORWARD_HEAD" # 전방 숙임 (나쁜 자세)
            status_color = (0, 0, 255) # 빨간색

        # 6개 주요 좌표 시각화 (파란색 점)
        for pt in [ear, eye, nose, shoulder, hip, knee]:
            cv2.circle(frame, pt, 4, (255, 0, 0), -1)

        # ------------------------------------------
        # 지속 시간 측정 및 5분 경고/모터 제어 로직
        # ------------------------------------------
        if current_status == "FORWARD_HEAD":
            if bad_posture_start_time is None:
                bad_posture_start_time = time.time()
            
            elapsed_time = int(time.time() - bad_posture_start_time)
            
            # 5분(300초) 이상 지속 처리
            if elapsed_time >= BAD_POSTURE_THRESHOLD_SEC and not alert_triggered:
                print("[ALERT] 나쁜 자세 5분 이상 지속! 경고 및 책상 조절 명령을 전송합니다.")
                send_arduino_command('A') # 'A': 책상 각도/높이 조절 명령
                alert_triggered = True
                
            # 화면에 지속 시간 표시
            cv2.putText(frame, f"Bad Posture: {elapsed_time}s / {BAD_POSTURE_THRESHOLD_SEC}s", 
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        else:
            # 자세가 다시 정상이 되면 타이머 리셋
            bad_posture_start_time = None
            if alert_triggered:
                print("[INFO] 자세 정상 복귀. 시스템 정지 상태 전달.")
                send_arduino_command('S') # 'S': 정지 명령
                alert_triggered = False

    # 화면에 현재 자세 상태 출력
    cv2.putText(frame, f"STATUS: {current_status}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

    cv2.imshow("Raspberry Pi 2 - Posture Control System", frame)

    # 'q' 키 누르면 종료
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if ser and ser.is_open:
    ser.close()
cv2.destroyAllWindows()

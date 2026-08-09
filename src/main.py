import cv2
import mediapipe as mp
import math
import time
import serial

# ==========================================
# 1. 아두이노 시리얼 통신 설정 (Hardware 연동)
# ==========================================
try:
    ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
    time.sleep(2)
    print("아두이노 시리얼 통신 연결 성공")
except Exception as e:
    print(f"시리얼 통신 연결 실패 (가상 테스트 모드): {e}")
    ser = None

def send_arduino_command(cmd):
    """아두이노로 제어 명령 전송"""
    if ser and ser.is_open:
        ser.write(f"{cmd}\n".encode('utf-8'))
        print(f"[SERIAL OUT] 명령 전송: {cmd}")

# ==========================================
# 2. MediaPipe Pose 및 기본 변수 설정
# ==========================================
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

# 라즈베리파이 2 최적화 (model_complexity=0)
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=0,
    smooth_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def calculate_vertical_angle(p1, p2):
    """두 점 p1(상체쪽), p2(하체쪽) 간 수직선 기준 기울기 각도(도) 계산"""
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    # 수직선(y축) 대비 수평 기울기 각도 계산
    angle_rad = math.atan2(abs(dx), abs(dy))
    return math.degrees(angle_rad)

# 지속 시간 측정 변수 (5분 = 300초)
BAD_POSTURE_THRESHOLD_SEC = 300  
bad_posture_start_time = None
alert_triggered = False

# 카메라 설정 (320x240 해상도 낮춤)
cap = cv2.VideoCapture(0)
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
    
    # 기본 상태: NORMAL
    current_status = "NORMAL"
    status_color = (0, 255, 0) # 초록색

    if results.pose_landmarks:
        landmarks = results.pose_landmarks.landmark
        
        # ------------------------------------------
        # 1. 6개 주요 좌표 추출 (측면 기준: 오른쪽)
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
        # 2. 체크리스트 요구사항 알고리즘 적용
        # ------------------------------------------
        # (1) 거북목 판단: 귀-어깨 기울기 각도 (기준치: 15도 이상 앞으로 쏠림)
        neck_angle = calculate_vertical_angle(ear, shoulder)
        
        # (2) 허리 굽음 판단: 어깨-골반 기울기 각도 (기준치: 20도 이상 숙여짐)
        back_angle = calculate_vertical_angle(shoulder, hip)
        
        # 상태 지정 (TURTLE_NECK, BENT_BACK, NORMAL)
        if neck_angle > 15:
            current_status = "TURTLE_NECK"
            status_color = (0, 0, 255) # 빨간색
        elif back_angle > 20:
            current_status = "BENT_BACK"
            status_color = (0, 165, 255) # 주황색

        # 6개 좌표 점 시각화
        for pt in [ear, eye, nose, shoulder, hip, knee]:
            cv2.circle(frame, pt, 4, (255, 0, 0), -1)

        # ------------------------------------------
        # 3. 나쁜 자세 지속 시간 및 경고 관리
        # ------------------------------------------
        if current_status in ["TURTLE_NECK", "BENT_BACK"]:
            if bad_posture_start_time is None:
                bad_posture_start_time = time.time()
            
            elapsed_time = int(time.time() - bad_posture_start_time)
            
            # 5분 이상 지속 시 동작
            if elapsed_time >= BAD_POSTURE_THRESHOLD_SEC and not alert_triggered:
                print(f"[ALERT] {current_status} 5분 이상 지속! 모터 구동 명령 전송")
                send_arduino_command('A') # 'A': 책상 각도/높이 조절
                alert_triggered = True
                
            # 지속 시간 표시
            cv2.putText(frame, f"Bad Time: {elapsed_time}s / {BAD_POSTURE_THRESHOLD_SEC}s", 
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        else:
            # NORMAL 복귀 시 타이머 초기화
            bad_posture_start_time = None
            if alert_triggered:
                send_arduino_command('S') # 'S': 정지
                alert_triggered = False

    # ------------------------------------------
    # 4. 화면(OpenCV 창)에 텍스트 출력 (체크리스트 요구사항)
    # ------------------------------------------
    cv2.putText(frame, f"STATUS: {current_status}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

    cv2.imshow("Raspberry Pi AI Posture Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if ser and ser.is_open:
    ser.close()
cv2.destroyAllWindows()

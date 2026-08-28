import math

class PostureEvaluator:
    """임계값 설정 기반 자세 평가 및 상태 판정 클래스"""
    
    @staticmethod
    def calculate_forward_neck_angle(p_ear, p_shoulder):
        dx = p_ear[0] - p_shoulder[0]
        dy = p_shoulder[1] - p_ear[1]
        
        if dy <= 0:
            return 0.0
        
        angle = math.degrees(math.atan2(dx, dy))
        return max(0.0, angle)

    @staticmethod
    def calculate_vertical_angle(p1, p2):
        dx = abs(p1[0] - p2[0])
        dy = abs(p1[1] - p2[1])
        if dy == 0:
            return 0.0
        return math.degrees(math.atan2(dx, dy))

    @classmethod
    def evaluate(cls, keypoints, input_size, scale, pad_x, pad_y, filter_neck, filter_back, config):
        l_ear, r_ear = keypoints[3], keypoints[4]
        l_shoulder, r_shoulder = keypoints[5], keypoints[6]
        l_hip, r_hip = keypoints[11], keypoints[12]

        r_score = r_ear[2] + r_shoulder[2] + r_hip[2]
        l_score = l_ear[2] + l_shoulder[2] + l_hip[2]

        if r_score >= l_score:
            ear, shoulder, hip = r_ear, r_shoulder, r_hip
        else:
            ear, shoulder, hip = l_ear, l_shoulder, l_hip

        min_vis = config.get('pose', {}).get('min_visibility', 0.05)

        if ear[2] > min_vis and shoulder[2] > min_vis:
            p_ear = (int((ear[1] * input_size - pad_x) / scale), int((ear[0] * input_size - pad_y) / scale))
            p_shoulder = (int((shoulder[1] * input_size - pad_x) / scale), int((shoulder[0] * input_size - pad_y) / scale))

            raw_neck = cls.calculate_forward_neck_angle(p_ear, p_shoulder)

            has_hip = hip[2] > min_vis
            if has_hip:
                p_hip = (int((hip[1] * input_size - pad_x) / scale), int((hip[0] * input_size - pad_y) / scale))
                raw_back = cls.calculate_vertical_angle(p_shoulder, p_hip)
            else:
                raw_back = 0.0

            neck_angle = filter_neck.update(raw_neck)
            back_angle = filter_back.update(raw_back)

            # YAML 임계값 적용
            neck_thresh = config.get('posture', {}).get('head_pitch_threshold_deg', 22.0)
            back_thresh = config.get('posture', {}).get('torso_angle_threshold_deg', 15.0)

            if neck_angle >= neck_thresh:
                pose = "TURTLE_NECK"
            elif has_hip and back_angle >= back_thresh:
                pose = "BENT_BACK"
            else:
                pose = "NORMAL"

            return pose, neck_angle, back_angle

        return "POSE_LOST", 0.0, 0.0

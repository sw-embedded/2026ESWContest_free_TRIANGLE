import time
import threading
import yaml
import os
from datetime import datetime

from camera.capture import CameraManager
from pose.detector import PoseDetector, ExponentialFilter
from posture.evaluator import PostureEvaluator
from posture.hold_timer import BadPostureHoldTimer
from actuator.serial_controller import SerialController
from ui.server import start_server


class PoseController:
    def __init__(self):
        self.current_status = {
            "pose": "INIT",
            "neck_angle": 0.0,
            "back_angle": 0.0,
            "updated_time": "-"
        }


def load_config(config_path="config/default.yaml"):
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def main():
    config = load_config("config/default.yaml")
    controller = PoseController()

    server_thread = threading.Thread(target=start_server, args=(controller,), daemon=True)
    server_thread.start()

    cam_cfg = config.get('camera', {})
    cam_manager = CameraManager(
        width=cam_cfg.get('width', 640),
        height=cam_cfg.get('height', 480)
    )

    pose_cfg = config.get('pose', {})
    detector = PoseDetector(model_type=pose_cfg.get('model', 'thunder'))

    act_cfg = config.get('actuator', {})
    serial_ctrl = SerialController(
        port=act_cfg.get('port', '/dev/ttyACM0'),
        baudrate=act_cfg.get('baudrate', 9600),
        enabled=act_cfg.get('enabled', True)
    )

    filter_neck = ExponentialFilter(alpha=0.3)
    filter_back = ExponentialFilter(alpha=0.3)
    bad_duration_sec = config.get('posture', {}).get('bad_duration_sec', 60)
    bad_posture_timer = BadPostureHoldTimer(bad_duration_sec)

    cam_manager.start()
    last_heartbeat = time.time()

    try:
        while True:
            now_str = datetime.now().strftime("%H:%M:%S")
            
            if time.time() - last_heartbeat > 2.0:
                serial_ctrl.send_heartbeat()
                last_heartbeat = time.time()

            frame = cam_manager.capture_array()
            if frame is None:
                bad_posture_timer.reset()
                time.sleep(0.1)
                continue

            keypoints, scale, pad_x, pad_y = detector.detect(frame)

            pose, neck_angle, back_angle = PostureEvaluator.evaluate(
                keypoints, detector.input_size, scale, pad_x, pad_y, 
                filter_neck, filter_back, config
            )

            controller.current_status = {
                "pose": pose,
                "neck_angle": neck_angle,
                "back_angle": back_angle,
                "updated_time": now_str
            }

            critical_posture = bad_posture_timer.update(pose)
            if critical_posture is not None:
                serial_ctrl.send_critical(critical_posture)
            elif pose == "NORMAL":
                serial_ctrl.send_normal()

            sample_interval = cam_cfg.get('sample_interval_sec', 0.05)
            time.sleep(sample_interval)

    finally:
        cam_manager.stop()
        serial_ctrl.close()


if __name__ == "__main__":
    main()

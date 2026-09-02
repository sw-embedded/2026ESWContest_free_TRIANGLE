import time
import threading
import yaml
from datetime import datetime
from pathlib import Path

from camera.capture import CameraManager
from pose.detector import PoseDetector, ExponentialFilter
from posture.evaluator import PostureEvaluator
from posture.command_coordinator import PostureCommandCoordinator
from posture.hold_timer import BadPostureHoldTimer
from actuator.serial_controller import SerialController
from monitor.status import PoseController
from ui.server import start_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"


def load_config(config_path=DEFAULT_CONFIG_PATH):
    config_path = Path(config_path)
    if not config_path.is_file():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")
    with config_path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def main():
    config = load_config()
    controller = PoseController()

    server_thread = threading.Thread(target=start_server, args=(controller,), daemon=True)
    server_thread.start()

    cam_cfg = config.get('camera', {})
    cam_manager = CameraManager(
        camera_num=cam_cfg.get('device_id', 0),
        width=cam_cfg.get('width', 640),
        height=cam_cfg.get('height', 480)
    )

    pose_cfg = config.get('pose', {})
    detector = PoseDetector(
        model_type=pose_cfg.get('model', 'thunder'),
        models_dir=PROJECT_ROOT / "models",
    )

    act_cfg = config.get('actuator', {})
    serial_ctrl = SerialController(
        port=act_cfg.get('port', '/dev/ttyACM0'),
        baudrate=act_cfg.get('baudrate', 9600),
        enabled=act_cfg.get('enabled', True),
        heartbeat_interval_sec=act_cfg.get('heartbeat_interval_sec', 2.0),
        status_interval_sec=act_cfg.get('status_interval_sec', 1.0),
        response_timeout_sec=act_cfg.get('response_timeout_sec', 10.0),
        reconnect_interval_sec=act_cfg.get('reconnect_interval_sec', 2.0),
    )
    controller.attach_serial_controller(serial_ctrl)

    filter_neck = ExponentialFilter(alpha=0.3)
    filter_back = ExponentialFilter(alpha=0.3)
    posture_cfg = config.get('posture', {})
    bad_duration_sec = posture_cfg.get('bad_duration_sec', 60)
    normal_restore_delay_sec = posture_cfg.get('normal_restore_delay_sec', 300)
    bad_posture_timer = BadPostureHoldTimer(bad_duration_sec)
    command_coordinator = PostureCommandCoordinator(
        serial_ctrl,
        normal_restore_delay_sec=normal_restore_delay_sec,
    )

    cam_manager.start()

    try:
        while True:
            now_str = datetime.now().strftime("%H:%M:%S")

            frame = cam_manager.capture_array()
            if frame is None:
                bad_posture_timer.reset()
                command_coordinator.update("POSE_LOST")
                controller.update_pose("POSE_LOST", 0.0, 0.0, now_str)
                time.sleep(0.1)
                continue

            keypoints, scale, pad_x, pad_y = detector.detect(frame)

            pose, neck_angle, back_angle = PostureEvaluator.evaluate(
                keypoints, detector.input_size, scale, pad_x, pad_y, 
                filter_neck, filter_back, config
            )

            critical_posture = bad_posture_timer.update(pose)
            command_coordinator.update(pose, critical_posture)

            controller.update_pose(
                pose, neck_angle, back_angle, now_str
            )

            sample_interval = cam_cfg.get('sample_interval_sec', 0.05)
            time.sleep(sample_interval)

    finally:
        cam_manager.stop()
        serial_ctrl.close()


if __name__ == "__main__":
    main()

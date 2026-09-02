from pathlib import Path

import cv2
import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        import tflite_runtime.interpreter as tflite
        Interpreter = tflite.Interpreter
    except ImportError:
        try:
            import tensorflow.lite as tflite
            Interpreter = tflite.Interpreter
        except ImportError:
            Interpreter = None


class ExponentialFilter:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.smoothed_val = None

    def update(self, val):
        if self.smoothed_val is None:
            self.smoothed_val = val
        else:
            self.smoothed_val = self.alpha * val + (1 - self.alpha) * self.smoothed_val
        return round(self.smoothed_val, 1)


class PoseDetector:
    SUPPORTED_MODELS = frozenset({"thunder", "lightning"})

    def __init__(self, model_type="thunder", models_dir=None):
        if Interpreter is None:
            raise RuntimeError(
                "TFLite interpreter가 없습니다. requirements/raspberrypi.txt의 "
                "ai-edge-litert를 설치하세요."
            )

        model_type = str(model_type).strip().lower()
        if model_type not in self.SUPPORTED_MODELS:
            supported = ", ".join(sorted(self.SUPPORTED_MODELS))
            raise ValueError(
                f"지원하지 않는 MoveNet 모델 종류입니다: {model_type!r} "
                f"(지원: {supported})"
            )

        if models_dir is None:
            models_dir = Path(__file__).resolve().parents[2] / "models"
        model_path = Path(models_dir) / f"movenet_singlepose_{model_type}.tflite"
        if not model_path.is_file():
            raise FileNotFoundError(
                "MoveNet 모델 파일을 찾을 수 없습니다: "
                f"{model_path}. models/README.md의 준비 방법을 확인하세요."
            )

        try:
            self.interpreter = Interpreter(model_path=str(model_path))
        except Exception as exc:
            raise RuntimeError(
                f"MoveNet 모델을 불러오지 못했습니다: {model_path}"
            ) from exc

        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        input_shape = tuple(int(value) for value in self.input_details[0]['shape'])
        if (
            len(input_shape) != 4
            or input_shape[0] != 1
            or input_shape[1] != input_shape[2]
            or input_shape[3] != 3
        ):
            raise ValueError(
                "예상하지 못한 MoveNet 입력 텐서 형태입니다: "
                f"{input_shape} (예상: (1, size, size, 3))"
            )
        self.input_size = input_shape[1]
        self.model_type = model_type
        self.model_path = model_path

        output_shape = tuple(
            int(value) for value in self.output_details[0]['shape']
        )
        if output_shape != (1, 1, 17, 3):
            raise ValueError(
                "예상하지 못한 MoveNet 출력 텐서 형태입니다: "
                f"{output_shape} (예상: (1, 1, 17, 3))"
            )

    def preprocess_letterbox(self, img):
        h, w, _ = img.shape
        scale = self.input_size / max(h, w)
        nh, nw = int(h * scale), int(w * scale)
        resized = cv2.resize(img, (nw, nh))

        padded = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        dy, dx = (self.input_size - nh) // 2, (self.input_size - nw) // 2
        padded[dy:dy+nh, dx:dx+nw] = resized
        return padded, scale, dx, dy

    def detect(self, frame):
        input_img, scale, pad_x, pad_y = self.preprocess_letterbox(frame)

        dtype = self.input_details[0]['dtype']
        if dtype == np.uint8:
            input_tensor = np.expand_dims(input_img, axis=0).astype(np.uint8)
        else:
            input_tensor = np.expand_dims(input_img, axis=0).astype(np.float32) / 255.0

        self.interpreter.set_tensor(self.input_details[0]['index'], input_tensor)
        self.interpreter.invoke()
        keypoints = self.interpreter.get_tensor(self.output_details[0]['index'])[0][0]

        return keypoints, scale, pad_x, pad_y

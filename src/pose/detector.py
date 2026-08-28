import cv2
import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        import tflite_runtime.interpreter as tflite
        Interpreter = tflite.Interpreter
    except ImportError:
        import tensorflow.lite as tflite
        Interpreter = tflite.Interpreter


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
    def __init__(self, model_type="thunder"):
        model_path = f"models/movenet_singlepose_{model_type}.tflite"
        try:
            self.interpreter = Interpreter(model_path=model_path)
        except Exception:
            fallback_path = "models/movenet_singlepose_lightning.tflite"
            self.interpreter = Interpreter(model_path=fallback_path)

        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_size = self.input_details[0]['shape'][1]

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

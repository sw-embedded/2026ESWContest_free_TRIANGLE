from picamera2 import Picamera2

class CameraManager:
    def __init__(self, width=640, height=480):
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(main={"size": (width, height), "format": "RGB888"})
        self.picam2.configure(config)

    def start(self):
        self.picam2.start()

    def capture_array(self):
        return self.picam2.capture_array()

    def stop(self):
        self.picam2.stop()

import unittest

from monitor.status import PoseController

try:
    from ui import server
except ModuleNotFoundError as error:
    if error.name != "flask":
        raise
    server = None


class FakeSerialController:
    def __init__(self):
        self.connected = False

    def get_status(self):
        return {
            "arduino_connected": self.connected,
            "correction_phase": "APPLIED" if self.connected else "IDLE",
        }


class PoseControllerTest(unittest.TestCase):
    def test_web_snapshot_always_merges_latest_serial_status(self):
        serial_controller = FakeSerialController()
        controller = PoseController()
        controller.attach_serial_controller(serial_controller)
        controller.update_pose("NORMAL", 1.5, 2.5, "10:10:10")

        self.assertFalse(controller.get_status()["arduino_connected"])

        serial_controller.connected = True
        status = controller.get_status()
        self.assertTrue(status["arduino_connected"])
        self.assertEqual(status["correction_phase"], "APPLIED")
        self.assertEqual(status["pose"], "NORMAL")

    @unittest.skipIf(server is None, "Flask is not installed")
    def test_status_api_reads_a_fresh_snapshot_without_cache(self):
        serial_controller = FakeSerialController()
        controller = PoseController()
        controller.attach_serial_controller(serial_controller)
        server.controller_instance = controller
        client = server.app.test_client()

        first = client.get("/api/status")
        self.assertFalse(first.get_json()["arduino_connected"])

        serial_controller.connected = True
        second = client.get("/api/status")
        self.assertTrue(second.get_json()["arduino_connected"])
        self.assertEqual(second.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()

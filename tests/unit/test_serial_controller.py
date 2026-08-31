import unittest

from actuator.serial_controller import SerialController


class FakeSerial:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []
        self.is_open = True

    def readline(self):
        if not self.responses:
            return b""
        return self.responses.pop(0)

    def write(self, message):
        self.writes.append(message)

    def close(self):
        self.is_open = False


class SerialControllerTest(unittest.TestCase):
    def test_reads_arduino_response_and_sends_protocol_commands(self):
        fake_serial = FakeSerial([
            b"DONE CORRECTION TURTLE_NECK\n",
            b"STATUS TILT_MM=5.00 TILT_MODE=0 HEIGHT_MODE=0 "
            b"CORRECTION_TYPE=TURTLE_NECK CORRECTION_PHASE=APPLIED "
            b"CURRENT=420 ESTOP=0\n",
        ])
        controller = SerialController(
            serial_factory=lambda *args, **kwargs: fake_serial,
            startup_delay_sec=0,
            start_reader=False,
        )

        self.assertTrue(controller._read_response_once())
        self.assertTrue(controller._read_response_once())
        self.assertTrue(controller.send_heartbeat())
        self.assertTrue(controller.send_status())

        status = controller.get_status()
        self.assertTrue(status["arduino_connected"])
        self.assertEqual(status["correction_phase"], "APPLIED")
        self.assertEqual(status["active_correction"], "TURTLE_NECK")
        self.assertEqual(status["current_sensor"], 420)
        self.assertEqual(status["tilt_mm"], 5.0)
        self.assertEqual(fake_serial.writes, [b"H\n", b"STATUS\n"])


if __name__ == "__main__":
    unittest.main()

import unittest
import time

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


class SlowFakeSerial(FakeSerial):
    def readline(self):
        response = super().readline()
        if not response:
            time.sleep(0.005)
        return response


class SerialControllerTest(unittest.TestCase):
    def test_reads_arduino_response_and_sends_protocol_commands(self):
        fake_serial = FakeSerial([
            b"DONE CORRECTION TURTLE_NECK\n",
            b"STATUS TILT_MM=5.00 TILT_MODE=0 HEIGHT_MODE=0 "
            b"CORRECTION_TYPE=TURTLE_NECK CORRECTION_PHASE=APPLIED "
            b"CURRENT=420 ESTOP=0 WATCHDOG_MS=300000\n",
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
        self.assertEqual(status["watchdog_timeout_sec"], 300.0)
        self.assertEqual(fake_serial.writes, [b"H\n", b"STATUS\n"])

    def test_connection_requires_a_recent_arduino_response(self):
        now = [0.0]
        fake_serial = FakeSerial([b"PONG\n"])
        controller = SerialController(
            serial_factory=lambda *args, **kwargs: fake_serial,
            startup_delay_sec=0,
            start_reader=False,
            response_timeout_sec=6.0,
            clock=lambda: now[0],
        )

        self.assertFalse(controller.get_status()["arduino_connected"])
        self.assertTrue(controller._read_response_once())
        self.assertTrue(controller.get_status()["arduino_connected"])

        now[0] = 6.1
        status = controller.get_status()
        self.assertFalse(status["arduino_connected"])
        self.assertIn("6초", status["serial_error"])
        self.assertTrue(controller.reconnect_event.is_set())

    def test_can_reconnect_after_initial_open_failure(self):
        fake_serial = FakeSerial([b"READY SMART_POSTURE_DESK_V5_NWCHR\n"])
        attempts = []

        def serial_factory(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("port missing")
            return fake_serial

        controller = SerialController(
            serial_factory=serial_factory,
            startup_delay_sec=0,
            start_reader=False,
        )

        self.assertFalse(controller.get_status()["arduino_connected"])
        self.assertTrue(controller._connect())
        self.assertTrue(controller._read_response_once())
        self.assertTrue(controller.get_status()["arduino_connected"])
        self.assertEqual(len(attempts), 2)

    def test_background_worker_sends_heartbeat_and_status(self):
        fake_serial = SlowFakeSerial([b"PONG\n"])
        controller = SerialController(
            serial_factory=lambda *args, **kwargs: fake_serial,
            startup_delay_sec=0,
            heartbeat_interval_sec=0.01,
            status_interval_sec=0.01,
            response_timeout_sec=1.0,
        )
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            if b"H\n" in fake_serial.writes and b"STATUS\n" in fake_serial.writes:
                break
            time.sleep(0.005)

        status = controller.get_status()
        controller.close()

        self.assertTrue(status["arduino_connected"])
        self.assertIn(b"H\n", fake_serial.writes)
        self.assertIn(b"STATUS\n", fake_serial.writes)


if __name__ == "__main__":
    unittest.main()

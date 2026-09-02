import unittest

from actuator.arduino_state import ArduinoState


class ArduinoStateTest(unittest.TestCase):
    def test_parses_status_response_for_web_ui(self):
        state = ArduinoState()

        state.handle_line(
            "STATUS TILT_ZERO_SET=1 TILT_MM=5.00 TILT_MODE=0 "
            "HEIGHT_MODE=0 CORRECTION_TYPE=TURTLE_NECK "
            "CORRECTION_PHASE=APPLIED CURRENT=487 LIMITS=0000 ESTOP=1 "
            "WATCHDOG_MS=300000"
        )

        status = state.snapshot()
        self.assertTrue(status["arduino_connected"])
        self.assertEqual(status["correction_phase"], "APPLIED")
        self.assertEqual(status["active_correction"], "TURTLE_NECK")
        self.assertEqual(status["current_sensor"], 487)
        self.assertEqual(status["tilt_mm"], 5.0)
        self.assertEqual(status["tilt_mode"], 0)
        self.assertEqual(status["height_mode"], 0)
        self.assertTrue(status["emergency_stop"])
        self.assertEqual(status["watchdog_timeout_sec"], 300.0)

    def test_tracks_correction_and_restore_lifecycle(self):
        state = ArduinoState()

        state.record_correction_requested("BENT_BACK")
        self.assertEqual(state.snapshot()["correction_phase"], "APPLYING")

        state.handle_line("DONE CORRECTION BENT_BACK")
        self.assertEqual(state.snapshot()["correction_phase"], "APPLIED")

        state.record_restore_requested()
        self.assertEqual(state.snapshot()["correction_phase"], "RESTORING")

        state.handle_line("DONE RESTORE")
        status = state.snapshot()
        self.assertEqual(status["correction_phase"], "IDLE")
        self.assertEqual(status["active_correction"], "NONE")

    def test_motion_error_sets_fault_phase(self):
        state = ArduinoState()
        state.record_correction_requested("TURTLE_NECK")

        state.handle_line("ERR OVERCURRENT")
        state.handle_line("PONG")

        status = state.snapshot()
        self.assertEqual(status["correction_phase"], "FAULT")
        self.assertEqual(status["last_arduino_error"], "ERR OVERCURRENT")


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = PROJECT_ROOT / "arduino" / "desk_controller" / "desk_controller.ino"


class FirmwareContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FIRMWARE_PATH.read_text(encoding="utf-8")

    def test_pin_map_matches_documented_wiring(self):
        expected = {
            "PIN_DIR": 2,
            "PIN_STEP": 3,
            "PIN_ACTUATOR_IN1": 7,
            "PIN_ACTUATOR_IN2": 8,
            "PIN_EMERGENCY_STOP": 12,
        }
        for name, pin in expected.items():
            self.assertRegex(
                self.source,
                rf"const uint8_t {name} = {pin};",
                msg=f"unexpected pin mapping for {name}",
            )

    def test_single_emergency_stop_and_three_second_watchdog_are_enabled(self):
        self.assertNotIn("PIN_LIMIT_SWITCH", self.source)
        self.assertNotIn("LIMIT_SWITCH_ENABLED", self.source)
        self.assertNotIn("PIN_TILT_ENABLE", self.source)
        self.assertNotIn("PIN_ACTUATOR_ENABLE", self.source)
        self.assertRegex(
            self.source,
            r"const unsigned long COMMAND_WATCHDOG_MS\s*=\s*3UL \* 1000UL;",
        )

    def test_automatic_turtle_neck_correction_moves_forty_millimeters(self):
        self.assertRegex(
            self.source,
            r"const float AUTO_TILT_DELTA_MM\s*=\s*40\.0f;",
        )

    def test_emergency_stop_is_checked_before_and_during_motion(self):
        self.assertGreaterEqual(
            len(re.findall(re.escape("emergencyStopActive()"), self.source)),
            5,
        )
        self.assertIn('stopAll(F("EMERGENCY"));', self.source)
        self.assertIn('Serial.println(F("ERR EMERGENCY_STOP"));', self.source)

    def test_stop_functions_remove_motor_drive_signals(self):
        self.assertRegex(
            self.source,
            r"void stopTilt\([^}]+digitalWrite\(PIN_STEP, LOW\);",
        )
        self.assertRegex(
            self.source,
            r"void stopHeightNow\([^}]+digitalWrite\(PIN_ACTUATOR_IN1, LOW\);"
            r"[^}]+digitalWrite\(PIN_ACTUATOR_IN2, LOW\);",
        )


if __name__ == "__main__":
    unittest.main()

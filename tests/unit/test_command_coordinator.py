import unittest

from posture.command_coordinator import PostureCommandCoordinator


class FakeSerialController:
    def __init__(self):
        self.phase = "IDLE"
        self.critical_commands = []
        self.normal_count = 0
        self.restore_count = 0

    def send_critical(self, posture_type):
        self.critical_commands.append(posture_type)

    def send_normal(self):
        self.normal_count += 1

    def send_restore(self):
        self.restore_count += 1
        return True

    def get_status(self):
        return {"correction_phase": self.phase}


class PostureCommandCoordinatorTest(unittest.TestCase):
    def test_sends_normal_only_when_pose_changes_to_normal(self):
        serial_controller = FakeSerialController()
        coordinator = PostureCommandCoordinator(serial_controller)

        coordinator.update("NORMAL")
        coordinator.update("NORMAL")
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.normal_count, 1)

    def test_forwards_critical_posture_once_from_hold_timer(self):
        serial_controller = FakeSerialController()
        coordinator = PostureCommandCoordinator(serial_controller)

        coordinator.update("TURTLE_NECK", "TURTLE_NECK")
        coordinator.update("TURTLE_NECK")

        self.assertEqual(
            serial_controller.critical_commands,
            ["TURTLE_NECK"],
        )

    def test_restores_once_when_applied_correction_returns_to_normal(self):
        serial_controller = FakeSerialController()
        coordinator = PostureCommandCoordinator(serial_controller)
        coordinator.update("BENT_BACK")
        serial_controller.phase = "APPLIED"

        coordinator.update("NORMAL")
        coordinator.update("NORMAL")
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.normal_count, 1)
        self.assertEqual(serial_controller.restore_count, 1)

    def test_allows_restore_again_after_previous_restore_finishes(self):
        serial_controller = FakeSerialController()
        coordinator = PostureCommandCoordinator(serial_controller)

        coordinator.update("TURTLE_NECK")
        serial_controller.phase = "APPLIED"
        coordinator.update("NORMAL")
        serial_controller.phase = "IDLE"
        coordinator.update("NORMAL")

        coordinator.update("BENT_BACK")
        serial_controller.phase = "APPLIED"
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.normal_count, 2)
        self.assertEqual(serial_controller.restore_count, 2)


if __name__ == "__main__":
    unittest.main()

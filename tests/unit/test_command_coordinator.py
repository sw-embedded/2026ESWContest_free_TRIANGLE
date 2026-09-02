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
        return True

    def send_normal(self):
        self.normal_count += 1
        return True

    def send_restore(self):
        self.restore_count += 1
        self.phase = "RESTORING"
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

    def test_restores_once_after_300_seconds_of_continuous_normal_posture(self):
        serial_controller = FakeSerialController()
        now = [0.0]
        coordinator = PostureCommandCoordinator(
            serial_controller,
            normal_restore_delay_sec=300,
            clock=lambda: now[0],
        )
        coordinator.update("BENT_BACK")
        serial_controller.phase = "APPLIED"

        coordinator.update("NORMAL")
        now[0] = 299.9
        coordinator.update("NORMAL")
        self.assertEqual(serial_controller.restore_count, 0)

        now[0] = 300.0
        coordinator.update("NORMAL")
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.normal_count, 1)
        self.assertEqual(serial_controller.restore_count, 1)

    def test_resets_restore_timer_when_pose_is_not_normal(self):
        serial_controller = FakeSerialController()
        now = [0.0]
        coordinator = PostureCommandCoordinator(
            serial_controller,
            normal_restore_delay_sec=300,
            clock=lambda: now[0],
        )
        serial_controller.phase = "APPLIED"

        coordinator.update("NORMAL")
        now[0] = 200.0
        coordinator.update("BENT_BACK")
        now[0] = 500.0
        coordinator.update("NORMAL")
        now[0] = 799.9
        coordinator.update("NORMAL")
        self.assertEqual(serial_controller.restore_count, 0)

        now[0] = 800.0
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.restore_count, 1)

    def test_defers_normal_command_while_correction_is_moving(self):
        serial_controller = FakeSerialController()
        coordinator = PostureCommandCoordinator(serial_controller)

        serial_controller.phase = "APPLYING"
        coordinator.update("NORMAL")
        self.assertEqual(serial_controller.normal_count, 0)

        serial_controller.phase = "RESTORING"
        coordinator.update("NORMAL")
        self.assertEqual(serial_controller.normal_count, 0)

        serial_controller.phase = "APPLIED"
        coordinator.update("NORMAL")
        self.assertEqual(serial_controller.normal_count, 1)

    def test_allows_restore_again_after_previous_restore_finishes(self):
        serial_controller = FakeSerialController()
        now = [0.0]
        coordinator = PostureCommandCoordinator(
            serial_controller,
            normal_restore_delay_sec=300,
            clock=lambda: now[0],
        )

        coordinator.update("TURTLE_NECK")
        serial_controller.phase = "APPLIED"
        coordinator.update("NORMAL")
        now[0] = 300.0
        coordinator.update("NORMAL")
        serial_controller.phase = "IDLE"
        coordinator.update("NORMAL")

        coordinator.update("BENT_BACK")
        serial_controller.phase = "APPLIED"
        now[0] = 400.0
        coordinator.update("NORMAL")
        now[0] = 700.0
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.normal_count, 2)
        self.assertEqual(serial_controller.restore_count, 2)

    def test_retries_restore_after_a_temporary_send_failure(self):
        serial_controller = FakeSerialController()
        now = [0.0]
        coordinator = PostureCommandCoordinator(
            serial_controller,
            normal_restore_delay_sec=300,
            clock=lambda: now[0],
        )
        attempts = [False, True]

        def send_restore():
            serial_controller.restore_count += 1
            result = attempts.pop(0)
            if result:
                serial_controller.phase = "RESTORING"
            return result

        serial_controller.send_restore = send_restore
        serial_controller.phase = "APPLIED"

        coordinator.update("NORMAL")
        now[0] = 300.0
        coordinator.update("NORMAL")
        coordinator.update("NORMAL")

        self.assertEqual(serial_controller.restore_count, 2)

    def test_retries_critical_command_after_a_temporary_send_failure(self):
        serial_controller = FakeSerialController()
        coordinator = PostureCommandCoordinator(serial_controller)
        attempts = [False, True]

        def send_critical(posture_type):
            serial_controller.critical_commands.append(posture_type)
            return attempts.pop(0)

        serial_controller.send_critical = send_critical

        coordinator.update("TURTLE_NECK", "TURTLE_NECK")
        coordinator.update("TURTLE_NECK")

        self.assertEqual(
            serial_controller.critical_commands,
            ["TURTLE_NECK", "TURTLE_NECK"],
        )


if __name__ == "__main__":
    unittest.main()

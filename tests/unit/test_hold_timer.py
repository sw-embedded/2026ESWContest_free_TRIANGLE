import unittest

from posture.hold_timer import BadPostureHoldTimer


class BadPostureHoldTimerTest(unittest.TestCase):
    def test_triggers_once_after_same_bad_posture_for_60_seconds(self):
        timer = BadPostureHoldTimer(60)

        self.assertIsNone(timer.update("TURTLE_NECK", now=100.0))
        self.assertIsNone(timer.update("TURTLE_NECK", now=159.9))
        self.assertEqual(timer.update("TURTLE_NECK", now=160.0),
                         "TURTLE_NECK")
        self.assertIsNone(timer.update("TURTLE_NECK", now=200.0))

    def test_switching_bad_posture_restarts_hold_time(self):
        timer = BadPostureHoldTimer(60)

        self.assertIsNone(timer.update("TURTLE_NECK", now=10.0))
        self.assertIsNone(timer.update("BENT_BACK", now=69.0))
        self.assertIsNone(timer.update("BENT_BACK", now=128.9))
        self.assertEqual(timer.update("BENT_BACK", now=129.0), "BENT_BACK")

    def test_non_bad_posture_resets_hold_time(self):
        for interruption in ("NORMAL", "POSE_LOST", "INIT"):
            with self.subTest(interruption=interruption):
                timer = BadPostureHoldTimer(60)

                self.assertIsNone(timer.update("BENT_BACK", now=0.0))
                self.assertIsNone(timer.update(interruption, now=59.0))
                self.assertIsNone(timer.update("BENT_BACK", now=60.0))
                self.assertEqual(timer.update("BENT_BACK", now=120.0),
                                 "BENT_BACK")

    def test_negative_hold_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            BadPostureHoldTimer(-1)


if __name__ == "__main__":
    unittest.main()

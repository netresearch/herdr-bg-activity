import unittest

from fakes import RecordingHerdr

from herdr_bg_activity import REFRESH_SECONDS, SOURCE, TTL_MS, HerdrError, Publisher

REPORT = "pane.report_metadata"


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.herdr = RecordingHerdr()
        self.publisher = Publisher(self.herdr)

    def publish(self, value, now, target="w1:p1"):
        self.publisher.publish("pane", target, {"bg": value}, now)

    def test_first_value_is_sent_with_ttl(self):
        self.publish("⧗ 1 shell", now=0.0)
        (params,) = self.herdr.reported(REPORT, "w1:p1")
        self.assertEqual(params["source"], SOURCE)
        self.assertEqual(params["tokens"], {"bg": "⧗ 1 shell"})
        self.assertEqual(params["ttl_ms"], TTL_MS)

    def test_empty_value_for_unknown_target_is_not_sent(self):
        self.publish(None, now=0.0)
        self.assertEqual(self.herdr.reports, [])
        self.assertEqual(self.publisher.targets("pane"), set())

    def test_unchanged_value_waits_for_refresh(self):
        self.publish("⧗ 1 shell", now=0.0)
        self.publish("⧗ 1 shell", now=REFRESH_SECONDS - 0.1)
        self.assertEqual(len(self.herdr.reported(REPORT, "w1:p1")), 1)
        self.publish("⧗ 1 shell", now=REFRESH_SECONDS)
        self.assertEqual(len(self.herdr.reported(REPORT, "w1:p1")), 2)

    def test_changed_value_is_sent_immediately(self):
        self.publish("⧗ 1 shell", now=0.0)
        self.publish("⧗ 2 shells", now=0.1)
        self.assertEqual(
            [p["tokens"]["bg"] for p in self.herdr.reported(REPORT, "w1:p1")],
            ["⧗ 1 shell", "⧗ 2 shells"],
        )

    def test_clearing_sends_null_once_without_ttl(self):
        self.publish("⧗ 1 shell", now=0.0)
        self.publish(None, now=0.1)
        self.publish(None, now=REFRESH_SECONDS * 3)
        reports = self.herdr.reported(REPORT, "w1:p1")
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[1]["tokens"], {"bg": None})
        self.assertNotIn("ttl_ms", reports[1])

    def test_target_herdr_no_longer_knows_is_forgotten(self):
        self.publish("⧗ 1 shell", now=0.0)
        self.herdr.missing.add("w1:p1")
        self.publish(None, now=0.1)
        self.assertEqual(self.publisher.targets("pane"), set())

    def test_other_errors_propagate_and_keep_the_target(self):
        self.publish("⧗ 1 shell", now=0.0)
        self.herdr.broken.add("w1:p1")
        with self.assertRaises(HerdrError) as caught:
            self.publish(None, now=0.1)
        self.assertEqual(caught.exception.code, "internal_error")
        self.assertEqual(self.publisher.targets("pane"), {"w1:p1"})


if __name__ == "__main__":
    unittest.main()

import datetime
import unittest

from tools import docker_runner


class DockerRunnerTests(unittest.TestCase):
    def test_parse_report_time(self):
        self.assertEqual(docker_runner.parse_report_time("13:05"), (13, 5))

    def test_parse_report_time_rejects_invalid_value(self):
        with self.assertRaisesRegex(RuntimeError, "HH:MM"):
            docker_runner.parse_report_time("25:00")

    def test_next_run_is_today_when_time_has_not_passed(self):
        now = datetime.datetime(2026, 8, 24, 12, 0).astimezone()
        target = docker_runner.next_run_at(now, 13, 0)
        self.assertEqual(target.date(), now.date())
        self.assertEqual((target.hour, target.minute), (13, 0))

    def test_next_run_is_tomorrow_when_time_has_passed(self):
        now = datetime.datetime(2026, 8, 24, 14, 0).astimezone()
        target = docker_runner.next_run_at(now, 13, 0)
        self.assertEqual(target.date(), now.date() + datetime.timedelta(days=1))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from glee_eval.diagnostics.wave5d_supervisor import ProcessSample, supervise


class Wave5DSupervisorTests(unittest.TestCase):
    def test_success_is_certified_once_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "marker"
            certificate = root / "certificate.json"
            result = supervise(
                [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"],
                certificate_path=certificate,
                deadline_seconds=5,
                poll_seconds=0.01,
                grace_seconds=0.1,
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(marker.read_text(), "x")
            self.assertEqual(json.loads(certificate.read_text()), result)
            self.assertEqual(result["limits"]["automatic_restarts"], 0)
            with self.assertRaises(FileExistsError):
                supervise(
                    [sys.executable, "-c", "pass"],
                    certificate_path=certificate,
                    deadline_seconds=5,
                )

    def test_disposable_time_violation_is_terminated_and_certified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "time.json"
            started = time.monotonic()
            result = supervise(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                certificate_path=certificate,
                deadline_seconds=0.10,
                poll_seconds=0.01,
                grace_seconds=0.05,
            )
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["termination_reason"], "monotonic_deadline_exceeded")
            self.assertTrue(result["termination_signal_sent"])
            self.assertTrue(certificate.exists())

    def test_disposable_memory_violation_is_terminated_and_certified(self) -> None:
        samples = iter([
            ProcessSample(1, 1, 1, (123,)),
            ProcessSample(65, 1, 1, (123,)),
        ])

        def fake_monitor(_pid: int) -> ProcessSample:
            return next(samples)

        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "memory.json"
            result = supervise(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                certificate_path=certificate,
                deadline_seconds=5,
                max_rss_bytes=64,
                poll_seconds=0.01,
                grace_seconds=0.05,
                monitor=fake_monitor,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["termination_reason"], "aggregate_rss_limit_exceeded")
            self.assertEqual(result["observed"]["peak_aggregate_rss_bytes"], 65)

    def test_real_process_memory_violation_is_observed_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = supervise(
                [sys.executable, "-c", "import time; x=bytearray(128*1024*1024); time.sleep(30)"],
                certificate_path=Path(directory) / "real-memory.json",
                deadline_seconds=5,
                max_rss_bytes=64 * 1024 * 1024,
                poll_seconds=0.01,
                grace_seconds=0.05,
            )
            self.assertEqual(result["termination_reason"], "aggregate_rss_limit_exceeded")
            self.assertGreater(result["observed"]["peak_aggregate_rss_bytes"], 64 * 1024 * 1024)

    def test_worker_limit_and_monitor_failure_are_fail_closed(self) -> None:
        scenarios = (
            (lambda _pid: ProcessSample(1, 7, 1, (123,)), "worker_thread_limit_exceeded"),
            (lambda _pid: (_ for _ in ()).throw(OSError("blocked")), "independent_monitor_unavailable"),
        )
        for monitor, reason in scenarios:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                result = supervise(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    certificate_path=Path(directory) / "certificate.json",
                    deadline_seconds=5,
                    max_worker_threads=6,
                    poll_seconds=0.01,
                    grace_seconds=0.05,
                    monitor=monitor,
                )
                self.assertEqual(result["termination_reason"], reason)
                self.assertEqual(result["status"], "failed")

    def test_expired_absolute_boundary_never_spawns_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-exist"
            result = supervise(
                [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"],
                certificate_path=Path(directory) / "expired.json",
                deadline_seconds=5,
                not_after_wall_time_ns=time.time_ns() - 1,
            )
            self.assertEqual(result["termination_reason"], "absolute_safe_shutdown_boundary_already_reached")
            self.assertIsNone(result["child_pid"])
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()

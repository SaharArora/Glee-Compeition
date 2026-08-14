"""Run the schema check as part of the ordinary suite.

This bug class -- a fact present under a name we do not read -- has now produced
confidently-wrong behaviour twice, and both times nothing raised. Leaving the
checker as a command someone has to remember to invoke would rely on exactly the
memory that failed the first two times, so it runs on every test invocation.

The live fixtures are always checked: they need no data, take milliseconds, and
cover the boundary where a mistranslation costs rated games.

The offline pass needs the ingested dataset, which is gitignored and multi-GB, so
it runs against a small prefix when the data is present and skips with a clear
reason when it is not. A skip is visible in the runner's output; a silent pass
would not be.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.diagnostics.schema_check import check_live, check_offline

EVENTS = Path(DEFAULT_DATA_DIR) / "processed" / "events.jsonl"

#: Enough real rows to exercise every family and both transcript shapes without
#: turning the unit suite into a minute-long job.
OFFLINE_SAMPLE = 4000


class LiveSchemaGateTests(unittest.TestCase):
    def test_live_fixtures_satisfy_their_contracts(self) -> None:
        report = check_live()

        self.assertTrue(report["clean"], f"live schema violations: {report['samples']}")
        self.assertGreater(report["fixtures_checked"], 0)


@unittest.skipUnless(EVENTS.exists(), f"ingested dataset not present at {EVENTS}")
class OfflineSchemaGateTests(unittest.TestCase):
    def test_real_events_satisfy_their_contracts(self) -> None:
        report = check_offline(DEFAULT_DATA_DIR, limit=OFFLINE_SAMPLE)

        self.assertTrue(report["clean"], f"offline schema violations: {report['samples']}")

    def test_the_sample_actually_exercises_the_transcript_contracts(self) -> None:
        """A clean result is only meaningful if the rows that broke were checked.

        Events are grouped by family in the file, so a prefix sample is all
        bargaining and reaches no persuasion transcript rows at all -- it would
        pass while covering nothing that has ever failed.
        """

        report = check_offline(DEFAULT_DATA_DIR, limit=OFFLINE_SAMPLE)

        self.assertGreater(report["events_scanned"], 0)
        self.assertGreater(report["transcript_rows_checked"], 0)
        self.assertGreater(len(report["families"]), 1, f"sample covered only {report['families']}")


if __name__ == "__main__":
    unittest.main()

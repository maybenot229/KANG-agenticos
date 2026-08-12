"""JobStore port-contract suite — fake and sqlite (13 §2.3).
Subclasses provide ``store`` wired to ``clock`` (a MovableClock)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kang.domain.ports.scheduler import Job

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _job(job_id: str = "job-1", **overrides) -> Job:
    fields = dict(
        id=job_id,
        name=job_id,
        schedule="hourly",
        catch_up="run_once_latest",
        created_at=ANCHOR,
    )
    fields.update(overrides)
    return Job(**fields)


class JobStoreContract:
    def test_register_then_list(self, store):
        store.register_job(_job("job-b", name="b"))
        store.register_job(_job("job-a", name="a"))
        assert [j.id for j in store.list_jobs()] == ["job-a", "job-b"]  # name order

    def test_register_is_idempotent_by_id(self, store):
        store.register_job(_job("job-1", schedule="hourly"))
        store.register_job(_job("job-1", schedule="daily"))
        assert store.list_jobs()[0].schedule == "daily"

    def test_last_slot_none_before_any_run(self, store):
        store.register_job(_job("job-1"))
        assert store.last_slot("job-1") is None

    def test_last_slot_is_max_started_any_outcome(self, store):
        store.register_job(_job("job-1"))
        run_a = store.start_run("job-1", ANCHOR + timedelta(hours=1), "c")
        store.finish_run(run_a, "ok", None)
        run_b = store.start_run("job-1", ANCHOR + timedelta(hours=2), "c")
        store.finish_run(run_b, "failed", "boom")
        assert store.last_slot("job-1") == ANCHOR + timedelta(hours=2)

    def test_record_skipped_advances_last_slot(self, store):
        store.register_job(_job("job-1"))
        store.record_skipped("job-1", ANCHOR + timedelta(hours=3))
        assert store.last_slot("job-1") == ANCHOR + timedelta(hours=3)

    def test_consecutive_failures_counts_trailing_failures(self, store):
        store.register_job(_job("job-1"))
        for hours, outcome in [(1, "ok"), (2, "failed"), (3, "failed")]:
            run = store.start_run("job-1", ANCHOR + timedelta(hours=hours), "c")
            store.finish_run(run, outcome, None)
        assert store.consecutive_failures("job-1") == 2

    def test_an_ok_resets_the_failure_streak(self, store):
        store.register_job(_job("job-1"))
        for hours, outcome in [(1, "failed"), (2, "ok"), (3, "failed")]:
            run = store.start_run("job-1", ANCHOR + timedelta(hours=hours), "c")
            store.finish_run(run, outcome, None)
        assert store.consecutive_failures("job-1") == 1

    def test_set_quarantined(self, store):
        store.register_job(_job("job-1"))
        store.set_quarantined("job-1", True)
        assert store.list_jobs()[0].quarantined is True

    def test_set_enabled(self, store):
        store.register_job(_job("job-1"))
        store.set_enabled("job-1", False)
        assert store.list_jobs()[0].enabled is False
        store.set_enabled("job-1", True)
        assert store.list_jobs()[0].enabled is True

    def test_set_enabled_in_txn(self, store):
        # ADR-021: the transaction-participating variant held_action.
        # approve's transactional-mode driver uses — same effect as
        # set_enabled() when called standalone (no shared transaction to
        # participate in here — that property is proven at the handler
        # level, not the store level).
        store.register_job(_job("job-1"))
        store.set_enabled_in_txn("job-1", False)
        assert store.list_jobs()[0].enabled is False

    def test_recover_incomplete_marks_unfinished_failed(self, store):
        store.register_job(_job("job-1"))
        store.start_run("job-1", ANCHOR + timedelta(hours=1), "c")  # never finished
        recovered = store.recover_incomplete(ANCHOR + timedelta(hours=2))
        assert recovered == 1
        # a second recovery finds nothing left unfinished
        assert store.recover_incomplete(ANCHOR + timedelta(hours=3)) == 0

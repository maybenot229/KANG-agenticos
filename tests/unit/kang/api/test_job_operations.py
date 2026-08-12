"""job.disable / job.enable handlers (ADR-021) — the gate half.

The claim under test: neither handler ever performs the effect itself —
every call, valid or not, either raises `confirmation_required` (having
created exactly one held action carrying the right operation/params) or
raises a validation/not-found error before ever touching a held action
at all. Driving an approved action to the actual effect is a different
code path (`held_action.approve`'s handler,
`tests/integration/sqlite/test_held_action_transactional_effect.py`),
deliberately not exercised here.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.held_action_store import FakeHeldActionStore
from kang.adapters.fakes.job_store import FakeJobStore
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    ConfirmationDeps,
    make_job_disable_handler,
    make_job_enable_handler,
)
from kang.domain.ports.scheduler import Job

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


@pytest.fixture
def wiring():
    clock = FakeClock()
    ids = (f"held-{n:04d}" for n in itertools.count())
    job_store = FakeJobStore(
        jobs=[
            Job(
                id="deadline_sweep",
                name="deadline_sweep",
                schedule="hourly",
                catch_up="run_once_latest",
                created_at=clock.now(),
            )
        ],
        clock=clock,
    )
    return {
        "clock": clock,
        "job_store": job_store,
        "held_actions": FakeHeldActionStore(),
        "new_id": lambda: next(ids),
    }


def _confirmation(wiring):
    return ConfirmationDeps(
        held_actions=wiring["held_actions"],
        clock=wiring["clock"],
        new_id=wiring["new_id"],
    )


def _disable_handler(wiring):
    return make_job_disable_handler(wiring["job_store"], _confirmation(wiring))


def _enable_handler(wiring):
    return make_job_enable_handler(wiring["job_store"], _confirmation(wiring))


class TestJobDisable:
    def test_always_raises_confirmation_required_never_disables_directly(self, wiring):
        handler = _disable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "deadline_sweep", "reason": "testing"})
        assert exc.value.code == "confirmation_required"
        # The effect never runs on this path — only approval drives it.
        assert wiring["job_store"].list_jobs()[0].enabled is True

    def test_creates_a_held_action_carrying_the_job_id_in_params(self, wiring):
        handler = _disable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "deadline_sweep", "reason": "testing"})
        held_id = exc.value.details["id"]
        held = wiring["held_actions"].get(held_id)
        assert held.operation == "job.disable"
        assert held.params == {"job_id": "deadline_sweep"}
        assert held.status == "pending"
        assert held.principal == "kang"
        assert held.reason == "testing"

    def test_missing_job_id_is_invalid_request(self, wiring):
        handler = _disable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"reason": "testing"})
        assert exc.value.code == "invalid_request"

    def test_missing_reason_is_invalid_request(self, wiring):
        handler = _disable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "deadline_sweep"})
        assert exc.value.code == "invalid_request"

    def test_blank_reason_is_invalid_request(self, wiring):
        handler = _disable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "deadline_sweep", "reason": "   "})
        assert exc.value.code == "invalid_request"

    def test_unknown_job_id_is_not_found_no_held_action_created(self, wiring):
        handler = _disable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "no-such-job", "reason": "testing"})
        assert exc.value.code == "not_found"
        assert wiring["held_actions"].pending() == []


class TestJobEnable:
    def test_always_raises_confirmation_required_never_enables_directly(self, wiring):
        wiring["job_store"].set_enabled("deadline_sweep", False)
        handler = _enable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "deadline_sweep", "reason": "testing"})
        assert exc.value.code == "confirmation_required"
        assert wiring["job_store"].list_jobs()[0].enabled is False

    def test_creates_a_held_action_naming_job_enable(self, wiring):
        handler = _enable_handler(wiring)
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {"job_id": "deadline_sweep", "reason": "testing"})
        held = wiring["held_actions"].get(exc.value.details["id"])
        assert held.operation == "job.enable"
        assert held.params == {"job_id": "deadline_sweep"}

"""`_check_transactional_effects_registered` — Item 2's registration-time
gate for `commit_mode="transactional"`, mirroring `registry/__init__.py`'s
own redrive gate in intent (fail at boot, never at approval time).

Runs at every `build_core()` call, inside `_build_consequential_handlers`,
right after `transactional_effects` is built — this is the earliest point
the registry's own declarations and the composition root's actual wiring
are both in scope. `build_core()` itself boots cleanly against the real,
complete table on every other test in this suite (`test_boot_catchup.py`
et al.) — that is the passing path's own proof. What was never proven
until this test: a *missing* entry is caught here, at boot, rather than
surfacing only if/when someone actually tries to approve a held action
naming that operation (`held_action_ops.py::_approve_transactional`'s own
`internal` error, the pre-existing but late failure mode this gate closes).
"""

from __future__ import annotations

import pytest

from kang.kernel.runtime.composition import _check_transactional_effects_registered


def test_the_real_transactional_effects_table_passes():
    """job.disable/job.enable are the only two operations that need an
    entry — held_action.approve/.cancel also declare commit_mode=
    "transactional" but describe their own effect, never a lookup target
    (see the checked function's own docstring); they must NOT be required
    here."""
    _check_transactional_effects_registered(
        {"job.disable": lambda p: None, "job.enable": lambda p: None}
    )


def test_a_missing_entry_fails_loudly_naming_the_operation():
    """The exact shape Item 2 asked for: an operation registered
    transactional with no matching effect fails here — at boot — not
    silently, and not only when someone later tries to approve it."""
    with pytest.raises(NotImplementedError, match="job.enable"):
        _check_transactional_effects_registered({"job.disable": lambda p: None})


def test_an_empty_table_fails_for_every_real_target():
    with pytest.raises(NotImplementedError):
        _check_transactional_effects_registered({})

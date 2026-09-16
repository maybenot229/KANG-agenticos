"""Read-pool query routing (ADR-036 D4, resumed).

Layer: kernel/runtime, carrying the SAME composition-root import
exemption as `composition.py` and `scheduler_wiring.py` — a third file,
same role, not a new one (ADR-023's own precedent; ADR-037 is this
file's own instance of it, split out when this slice pushed
`composition.py` past the size lint's hard limits). Registered by exact
name in `tools/importlinter.toml`.

Constitutional home: 07_DATABASE DB-001 (the read pool), ADR-036 D4 (the
three-phase split, the per-call query-handler-construction finding),
12_API §5 (the pipeline STEPS this orchestrates are defined in
`api/dispatch.py`'s `Dispatcher.prepare_query`/`run_query_handler`/
`finish_query`/`fail_query` — this module only threads them across the
write-executor and read pool, never redefines them).

`composition.py`'s `_build_core_locked` calls `_build_query_handlers`
and `serve` calls `_dispatch_query` exactly as they called their own
private functions before the split — the public seam (`build_core`,
`serve`) is unchanged, per ADR-023's own precedent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kang.adapters.sqlite.competition_store import SqliteCompetitionStore
from kang.adapters.sqlite.connection_pool import ReadPool, WriteExecutor
from kang.adapters.sqlite.deadline_store import SqliteDeadlineStore
from kang.adapters.sqlite.goal_store import SqliteGoalStore
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.adapters.sqlite.milestone_store import SqliteMilestoneStore
from kang.adapters.sqlite.project_store import SqliteProjectStore
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.api.dispatch import ApiRequest
from kang.api.errors import ApiError
from kang.api.operations import (
    make_audit_list_handler,
    make_competition_list_handler,
    make_deadline_list_handler,
    make_explain_invocation_handler,
    make_explain_stub_handler,
    make_goal_list_handler,
    make_held_action_list_handler,
    make_invocation_list_handler,
    make_milestone_list_handler,
    make_permission_list_handler,
    make_project_list_handler,
    make_registry_get_handler,
    make_task_get_handler,
)

if TYPE_CHECKING:  # avoids a runtime cycle with composition.py (ADR-037)
    from kang.kernel.runtime.composition import Core, _HandlerWiring

__all__ = ["_build_query_handlers", "_dispatch_query"]


def _build_query_handlers(w: "_HandlerWiring") -> dict:
    """Per-call factories for the 16 query-kind operations ADR-036 D4
    (resumed) routes to the read pool: `name -> Callable[[connection],
    Handler]`, built fresh against whichever read-pool connection is
    checked out for that call — never against `w.connection` (the write
    connection `composition.py`'s `_build_handlers` uses). `w.audit` and
    `w.permission_engine` ARE shared, boot-time instances, reused as-is:
    `AuditService` is file-backed (`JsonlAuditLog`), not sqlite, and its
    read paths (`records`/`chain_head`) open their own file handle per
    call, so concurrent read-pool callers are already safe without
    per-call reconstruction; the permission engine holds in-memory
    grants loaded once at boot, no connection at all.

    `system.health` is the one query operation NOT here (see
    `composition.py`'s `_build_handlers` instead): its `backups`
    dependency (`SqliteBackupService`) needs both `kang.db` AND
    `events/eventlog.db`, and `ReadPool` opens only one connection type
    per worker today — a gap named, not silently worked around."""
    return {
        "registry.get": lambda conn: make_registry_get_handler(),
        "permission.list": lambda conn: make_permission_list_handler(
            w.permission_engine
        ),
        "task.get": lambda conn: make_task_get_handler(SqliteTaskStore(conn, w.clock)),
        "deadline.list": lambda conn: make_deadline_list_handler(
            SqliteDeadlineStore(conn, w.clock)
        ),
        "explain.invocation": lambda conn: make_explain_invocation_handler(
            SqliteInvocationStore(conn), w.audit
        ),
        "explain.plan_item": lambda conn: make_explain_stub_handler("plan item"),
        "explain.notification": lambda conn: make_explain_stub_handler("notification"),
        "explain.suggestion": lambda conn: make_explain_stub_handler("suggestion"),
        "explain.memory": lambda conn: make_explain_stub_handler("memory record"),
        "audit.list": lambda conn: make_audit_list_handler(w.audit, w.clock),
        "invocation.list": lambda conn: make_invocation_list_handler(
            SqliteInvocationStore(conn)
        ),
        "held_action.list": lambda conn: make_held_action_list_handler(
            SqliteHeldActionStore(conn)
        ),
        **_build_query_project_cluster_handlers(w),
    }


def _build_query_project_cluster_handlers(w: "_HandlerWiring") -> dict:
    """project/competition/milestone/goal `.list` — the read-pool-routed
    mirror of `composition.py`'s `_build_project_cluster_handlers` (11 §4
    size lint, same reason that one was extracted)."""
    return {
        "project.list": lambda conn: make_project_list_handler(
            SqliteProjectStore(conn, w.clock)
        ),
        "competition.list": lambda conn: make_competition_list_handler(
            SqliteCompetitionStore(conn)
        ),
        "milestone.list": lambda conn: make_milestone_list_handler(
            SqliteMilestoneStore(conn, w.clock)
        ),
        "goal.list": lambda conn: make_goal_list_handler(
            SqliteGoalStore(conn, w.clock)
        ),
    }


async def _dispatch_query(
    core: "Core",
    request: ApiRequest,
    write_executor: WriteExecutor,
    read_pool: ReadPool,
) -> dict:
    """A read-pool-routed query dispatch is three hops, not one atomic
    write-executor submission — write-executor (`prepare_query`:
    auth/validate/checks/record-start), read pool (the handler itself,
    built fresh against that call's own checked-out connection),
    write-executor (`finish_query`/`fail_query` + response). This is the
    only place that sequence exists; `Dispatcher` itself stays fully
    synchronous — see its own methods' docstrings — so nothing here
    duplicates the pipeline's own logic, only its threading. Mirrors
    `Dispatcher.dispatch()`'s own top-level error handling via
    `error_envelope`, since this path never calls `dispatch()` itself."""
    correlation_id = core.new_id()  # pure (uuid7 + clock) — safe on any
    #   thread, unlike everything else this function touches.
    try:
        entry, context = await write_executor.submit(
            lambda core: core.dispatcher.prepare_query(request, correlation_id)
        )
        try:
            result = await read_pool.submit(
                lambda conn: core.dispatcher.run_query_handler(
                    entry["name"], conn, context, request.params
                )
            )
        except ApiError:
            await write_executor.submit(
                lambda core: core.dispatcher.fail_query(correlation_id)
            )
            raise
        return await write_executor.submit(
            lambda core: core.dispatcher.finish_query(context, result)
        )
    except Exception as exc:
        # `except ... as exc` is implicitly deleted at the end of this
        # block (a Python closure-over-except-name pitfall) — rebind to
        # a plain local before the lambda captures it.
        caught = exc
        return await write_executor.submit(
            lambda core: core.dispatcher.error_envelope(caught, correlation_id)
        )

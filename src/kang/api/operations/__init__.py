"""Operation handlers — the thin glue from the contract to domain services.

Layer: api.
Constitutional home: 12_API §2 (handlers contain dispatch-to-domain only; an
`if` about domain semantics here is a defect), §7 (commands), §8 (queries),
§12 (explainability). Each handler is built with its domain dependencies
bound at the composition root; the dispatcher supplies (context, params).

Split into one module per operation family (2026-08-06) — the flat
`operations.py` this package replaced crossed the size lint's 800-line
hard limit the moment `project.create`/`.list` (ADR-013) landed; per
11_CODING §25/CLAUDE.md §11, a lint failure is answered by splitting the
unit, never by relaxing the limit. This `__init__.py` re-exports every
name the flat module used to export, so `from kang.api.operations import
make_X_handler` (composition.py, every `tests/unit/kang/api/test_*.py`)
needed zero changes — a pure reorganization, not a behavior or contract
change.
"""

from __future__ import annotations

from kang.api.operations.competition_ops import (
    COMPETITIONS_PRINCIPAL,
    make_competition_create_handler,
    make_competition_list_handler,
)
from kang.api.operations.consequential import (
    ConfirmationDeps,
    ConfirmationRequest,
    require_confirmation,
)
from kang.api.operations.deadline_ops import (
    DEADLINES_PRINCIPAL,
    make_deadline_create_handler,
    make_deadline_list_handler,
    make_deadline_sweep_handler,
)
from kang.api.operations.explain_ops import (
    make_explain_invocation_handler,
    make_explain_stub_handler,
)
from kang.api.operations.goal_ops import (
    GOALS_PRINCIPAL,
    make_goal_achieve_handler,
    make_goal_create_handler,
    make_goal_list_handler,
    make_goal_retire_handler,
    make_goal_revise_handler,
)
from kang.api.operations.held_action_ops import (
    make_held_action_approve_handler,
    make_held_action_cancel_handler,
    make_held_action_expire_handler,
    make_held_action_list_handler,
)
from kang.api.operations.job_ops import (
    make_job_disable_handler,
    make_job_enable_handler,
)
from kang.api.operations.milestone_ops import (
    MILESTONES_PRINCIPAL,
    make_milestone_create_handler,
    make_milestone_drop_handler,
    make_milestone_list_handler,
    make_milestone_miss_handler,
    make_milestone_reach_handler,
)
from kang.api.operations.notification_ops import make_notification_ack_handler
from kang.api.operations.plan_ops import (
    PLANNER_PRINCIPAL,
    PlannerDeps,
    make_plan_generate_handler,
)
from kang.api.operations.project_ops import (
    PROJECTS_PRINCIPAL,
    make_project_complete_handler,
    make_project_create_handler,
    make_project_list_handler,
)
from kang.api.operations.registry_ops import make_registry_get_handler
from kang.api.operations.system_ops import (
    make_audit_list_handler,
    make_invocation_list_handler,
    make_permission_list_handler,
    make_system_health_handler,
)
from kang.api.operations.task_ops import (
    TASKS_PRINCIPAL,
    make_task_complete_handler,
    make_task_create_handler,
    make_task_get_handler,
)

__all__ = [
    "COMPETITIONS_PRINCIPAL",
    "ConfirmationDeps",
    "ConfirmationRequest",
    "DEADLINES_PRINCIPAL",
    "GOALS_PRINCIPAL",
    "MILESTONES_PRINCIPAL",
    "PLANNER_PRINCIPAL",
    "PROJECTS_PRINCIPAL",
    "PlannerDeps",
    "TASKS_PRINCIPAL",
    "make_audit_list_handler",
    "make_competition_create_handler",
    "make_competition_list_handler",
    "make_deadline_create_handler",
    "make_deadline_list_handler",
    "make_deadline_sweep_handler",
    "make_explain_invocation_handler",
    "make_explain_stub_handler",
    "make_goal_achieve_handler",
    "make_goal_create_handler",
    "make_goal_list_handler",
    "make_goal_retire_handler",
    "make_goal_revise_handler",
    "make_held_action_approve_handler",
    "make_held_action_cancel_handler",
    "make_held_action_expire_handler",
    "make_held_action_list_handler",
    "make_invocation_list_handler",
    "make_job_disable_handler",
    "make_job_enable_handler",
    "make_milestone_create_handler",
    "make_milestone_drop_handler",
    "make_milestone_list_handler",
    "make_milestone_miss_handler",
    "make_milestone_reach_handler",
    "make_notification_ack_handler",
    "make_permission_list_handler",
    "make_plan_generate_handler",
    "make_project_complete_handler",
    "make_project_create_handler",
    "make_project_list_handler",
    "make_registry_get_handler",
    "make_system_health_handler",
    "make_task_complete_handler",
    "make_task_create_handler",
    "make_task_get_handler",
    "require_confirmation",
]

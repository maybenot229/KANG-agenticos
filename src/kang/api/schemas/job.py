"""Request schema for `job.disable`/`job.enable` (ADR-010 Ruling 1, ADR-021).

Layer: api.
Constitutional home: 12_API §7 (consequential commands return
`confirmation_required` + a `held_action`, never a normal success
response on the operation itself), 05_AGENTS Appendix D (`job.enable`/
`.disable (core jobs)`, the closed consequential list), ADR-021 (the
first real instance of this contract, built end to end).

No response schema: unlike every other paired request/response in this
package, `job.disable`/`job.enable`'s own handler never returns a success
result on any call — it always either raises `confirmation_required`
(no prior approval) or is never reached directly again (the approved
effect is driven by a separate function, `TRANSACTIONAL_EFFECTS`,
composition.py — ADR-021's own ruling that re-dispatching through this
operation's registered handler would open a second transaction and
break the one-transaction promise). A `response_schema` would document a
shape that can never occur.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["JobDisableRequest", "JobEnableRequest"]


class JobDisableRequest(BaseModel):
    """`job.disable` params (operations.py::make_job_disable_handler).
    `reason` is required and UI-collected — `HeldAction.reason`'s own
    docstring calls it "the requester's stated reasoning," never
    synthesized by the handler."""

    job_id: str
    reason: str = Field(min_length=1)


class JobEnableRequest(BaseModel):
    """`job.enable` params (operations.py::make_job_enable_handler)."""

    job_id: str
    reason: str = Field(min_length=1)

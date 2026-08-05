"""permission.list — 09_UI §7's System-domain permission screen.

The claim: the handler reflects `PermissionEngine.snapshot()` verbatim
(no filtering, no reordering beyond what the engine already returns) and
attaches a plain-language consequence sentence per scope, falling back
honestly rather than fabricating one for a scope this session didn't
write a description for.
"""

from __future__ import annotations

from kang.api.dispatch import HandlerContext
from kang.api.operations import make_permission_list_handler
from kang.kernel.permissions.engine import PermissionEngine

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


def _list(engine: PermissionEngine) -> dict:
    handler = make_permission_list_handler(engine)
    return handler(CONTEXT, {})


def test_lists_every_principal():
    engine = PermissionEngine(
        {"kang": ("*",), "kernel:tasks": ("events.publish:kang",)}
    )
    result = _list(engine)
    principals = {g["principal"] for g in result["grants"]}
    assert principals == {"kang", "kernel:tasks"}


def test_wildcard_gets_the_kang_only_consequence():
    engine = PermissionEngine({"kang": ("*",)})
    (kang_grant,) = _list(engine)["grants"]
    (scope_grant,) = kang_grant["scopes"]
    assert scope_grant["scope"] == "*"
    assert "Kang's own first-party session" in scope_grant["consequence"]


def test_known_scope_family_gets_a_real_sentence():
    engine = PermissionEngine({"kernel:tasks": ("events.publish:kang",)})
    (grant,) = _list(engine)["grants"]
    (scope_grant,) = grant["scopes"]
    assert scope_grant["scope"] == "events.publish:kang"
    assert scope_grant["consequence"].startswith("Can publish facts")


def test_unknown_scope_family_gets_an_honest_fallback_not_a_fabrication():
    engine = PermissionEngine({"agent:mystery": ("plugin.frobnicate:widget",)})
    (grant,) = _list(engine)["grants"]
    (scope_grant,) = grant["scopes"]
    assert "No plain-language description written yet" in scope_grant["consequence"]
    assert "plugin.frobnicate" in scope_grant["consequence"]


def test_empty_engine_lists_nothing():
    engine = PermissionEngine({})
    assert _list(engine) == {"grants": []}

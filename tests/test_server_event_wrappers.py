import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence, TypeAlias, cast

import pytest

import openplot.server as server


EXTRACTED_SERVER_EVENT_HELPERS = (
    "_broadcast",
    "_broadcast_plot_mode_message_update",
    "_broadcast_plot_mode_preview",
)
FunctionNode: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef


def _read_module_ast(module_path: Path) -> tuple[ast.Module, dict[str, FunctionNode]]:
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return tree, functions


def _server_module_reference(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
        and isinstance(node.slice, ast.Name)
        and node.slice.id == "__name__"
    )


def _returns_none(function: FunctionNode) -> bool:
    return (
        function.returns is not None
        and isinstance(function.returns, ast.Constant)
        and function.returns.value is None
    )


def _dump_nodes(nodes: Sequence[ast.expr | None]) -> list[str | None]:
    return [None if node is None else ast.dump(node) for node in nodes]


def _signature_shape(
    function: FunctionNode,
    *,
    drop_leading_server_module: bool = False,
) -> dict[str, object]:
    posonlyargs = [arg.arg for arg in function.args.posonlyargs]
    args = [arg.arg for arg in function.args.args]
    if drop_leading_server_module:
        if args:
            assert args[0] == "server_module"
            args = args[1:]
        else:
            raise AssertionError("Extracted helper must accept server_module first")
    return {
        "posonlyargs": posonlyargs,
        "args": args,
        "vararg": None if function.args.vararg is None else function.args.vararg.arg,
        "kwonlyargs": [arg.arg for arg in function.args.kwonlyargs],
        "kwarg": None if function.args.kwarg is None else function.args.kwarg.arg,
        "defaults": _dump_nodes(function.args.defaults),
        "kw_defaults": _dump_nodes(function.args.kw_defaults),
    }


def _body_without_docstring(function: FunctionNode) -> list[ast.stmt]:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    ):
        if isinstance(body[0].value.value, str):
            return body[1:]
    return body


def _assert_pre_extraction_contract(functions: dict[str, FunctionNode]) -> None:
    expected_signatures = {
        "_broadcast": {
            "posonlyargs": [],
            "args": ["event"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
        "_broadcast_plot_mode_message_update": {
            "posonlyargs": [],
            "args": ["state", "message"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
        "_broadcast_plot_mode_preview": {
            "posonlyargs": [],
            "args": ["state"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
    }

    for helper_name, expected_signature in expected_signatures.items():
        function = functions[helper_name]
        assert _signature_shape(function) == expected_signature
        assert _returns_none(function)

    message_update_body = _body_without_docstring(
        functions["_broadcast_plot_mode_message_update"]
    )
    assert len(message_update_body) == 1
    assert isinstance(message_update_body[0], ast.Expr)
    assert isinstance(message_update_body[0].value, ast.Await)

    preview_body = _body_without_docstring(functions["_broadcast_plot_mode_preview"])
    assert len(preview_body) == 2
    for statement in preview_body:
        assert isinstance(statement, ast.Expr)
        assert isinstance(statement.value, ast.Await)

    broadcast_body = _body_without_docstring(functions["_broadcast"])
    assert broadcast_body
    assert isinstance(broadcast_body[0], ast.Assign)
    assert isinstance(broadcast_body[-2], ast.For)
    assert isinstance(broadcast_body[-1], ast.For)


def test_server_event_helpers_are_thin_wrappers_when_extracted() -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_events' in bound_helpers:
        assert set(EXTRACTED_SERVER_EVENT_HELPERS) <= set(bound_helpers['_server_events'])
        for helper_name in EXTRACTED_SERVER_EVENT_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_path = Path(server.__file__).resolve()
    events_path = server_path.with_name("server_events.py")
    _, functions = _read_module_ast(server_path)

    for helper_name in EXTRACTED_SERVER_EVENT_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"

    if not events_path.exists():
        _assert_pre_extraction_contract(functions)
        return

    _, event_functions = _read_module_ast(events_path)

    for helper_name in EXTRACTED_SERVER_EVENT_HELPERS:
        function = functions[helper_name]
        event_function = event_functions.get(helper_name)
        assert event_function is not None, f"Missing extracted helper for {helper_name}"
        assert _signature_shape(function) == _signature_shape(
            event_function, drop_leading_server_module=True
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        if _returns_none(event_function):
            assert isinstance(statement, (ast.Expr, ast.Return))
        else:
            assert isinstance(statement, ast.Return)

        call = statement.value
        if isinstance(call, ast.Await):
            call = call.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "_server_events"
        assert call.func.attr == helper_name
        assert call.args, f"{helper_name} should pass the server module first"
        assert _server_module_reference(call.args[0])

        wrapper_args = [
            *(arg.arg for arg in function.args.posonlyargs),
            *(arg.arg for arg in function.args.args),
        ]
        assert [
            argument.id for argument in call.args[1:] if isinstance(argument, ast.Name)
        ] == wrapper_args
        assert len(call.args[1:]) == len(wrapper_args)

        assert [
            keyword.arg for keyword in call.keywords if keyword.arg is not None
        ] == [arg.arg for arg in function.args.kwonlyargs]
        for keyword in call.keywords:
            if keyword.arg is None:
                assert function.args.kwarg is not None
                assert isinstance(keyword.value, ast.Name)
                assert keyword.value.id == function.args.kwarg.arg
                continue
            assert isinstance(keyword.value, ast.Name)
            assert keyword.value.id == keyword.arg


@pytest.mark.anyio
async def test_broadcast_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeJson:
        @staticmethod
        def dumps(event: dict) -> str:
            calls.append(("dumps", event["type"]))
            return "patched-payload"

    class FakeWebSocket:
        async def send_text(self, payload: str) -> None:
            calls.append(("send_text", payload))

    fake_clients = {FakeWebSocket()}

    monkeypatch.setattr(server, "json", FakeJson)
    monkeypatch.setattr(server, "_runtime_ws_clients", lambda: fake_clients)

    await server._broadcast({"type": "plot_mode_completed"})

    assert calls == [
        ("dumps", "plot_mode_completed"),
        ("send_text", "patched-payload"),
    ]


@pytest.mark.anyio
async def test_broadcast_plot_mode_message_update_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    class FakeMessage:
        def model_dump(self, *, mode: str) -> dict:
            assert mode == "json"
            return {"id": "message-id", "content": "Draft ready"}

    state = SimpleNamespace(id="plot-mode-state", updated_at="2026-03-26T00:00:00Z")

    async def fake_broadcast(event: dict) -> None:
        calls.append(event)

    monkeypatch.setattr(server, "_broadcast", fake_broadcast)

    await server._broadcast_plot_mode_message_update(
        cast(Any, state), cast(Any, FakeMessage())
    )

    assert calls == [
        {
            "type": "plot_mode_message_updated",
            "plot_mode_id": "plot-mode-state",
            "updated_at": "2026-03-26T00:00:00Z",
            "message": {"id": "message-id", "content": "Draft ready"},
        }
    ]


@pytest.mark.anyio
async def test_broadcast_plot_mode_preview_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    state = SimpleNamespace(id="plot-mode-state", plot_type="raster")

    async def fake_state_broadcast(current_state) -> None:
        calls.append(("state", current_state.id))

    async def fake_broadcast(event: dict) -> None:
        calls.append(("event", event["reason"]))

    monkeypatch.setattr(server, "_broadcast_plot_mode_state", fake_state_broadcast)
    monkeypatch.setattr(server, "_broadcast", fake_broadcast)

    await server._broadcast_plot_mode_preview(cast(Any, state))

    assert calls == [
        ("state", "plot-mode-state"),
        ("event", "plot_mode_preview"),
    ]

import ast
from pathlib import Path
from typing import Sequence

import openplot.server as server
import openplot.server_runners as server_runners


EXTRACTED_SERVER_RUNNER_HELPERS = (
    "_runner_default_model_id",
    "_normalize_runner_session_id",
    "_runner_session_id_for_session",
    "_set_runner_session_id_for_session",
    "_clear_runner_session_id_for_session",
    "_runner_session_id_for_plot_mode",
    "_set_runner_session_id_for_plot_mode",
    "_clear_runner_session_id_for_plot_mode",
    "_runner_tools_root",
    "_managed_command_path",
    "_resolve_command_path",
    "_subprocess_env",
    "_no_window_kwargs",
    "_hidden_window_kwargs",
    "_shell_join",
    "_backend_url_from_port_file",
    "_write_fix_runner_shims",
    "_write_fix_runner_shims_unix",
    "_write_fix_runner_shims_windows",
    "_resolve_claude_cli_command",
    "_runner_launch_probe",
    "_opencode_auth_file_path",
    "_opencode_auth_file_has_credentials",
    "_opencode_auth_list_has_credentials",
    "_runner_auth_command",
    "_runner_auth_launch_parts",
    "_runner_auth_launch_command",
    "_powershell_quote",
    "_runner_auth_windows_command",
    "_runner_auth_guide_url",
    "_runner_auth_instructions",
    "_runner_auth_probe",
    "_runner_auth_launch_supported",
    "_apple_script_quote",
    "_launch_runner_auth_terminal",
    "_detect_runner_availability",
    "_runner_host_platform",
    "_winget_available",
    "_runner_guide_url",
    "_runner_install_supported",
    "_runner_default_status",
    "_runner_install_job_snapshot",
    "_latest_runner_install_job_snapshot",
    "_build_runner_status_payload",
    "_create_runner_install_job",
    "_update_runner_install_job",
    "_append_runner_install_log",
    "_run_install_subprocess",
    "_resolve_runner_executable_path",
    "_install_runner_via_script",
    "_download_url_to_file",
    "_run_download_subprocess",
    "_read_url_bytes",
    "_parse_semver_parts",
    "_normalize_release_version",
    "_fetch_latest_release_payload",
    "_default_update_status_payload",
    "_update_status_cache_path",
    "_load_update_status_disk_cache",
    "_store_update_status_cache",
    "_build_update_status_payload_impl",
    "_build_update_status_payload",
)


def _read_module_ast(module) -> tuple[ast.Module, dict[str, ast.FunctionDef]]:
    module_path = Path(module.__file__).resolve()
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    return tree, functions


def _is_server_module_reference(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
        and isinstance(node.slice, ast.Name)
        and node.slice.id == "__name__"
    )


def _positional_parameter_names(function: ast.FunctionDef) -> list[str]:
    return [
        *(arg.arg for arg in function.args.posonlyargs),
        *(arg.arg for arg in function.args.args),
    ]


def _returns_none(function: ast.FunctionDef) -> bool:
    return (
        function.returns is not None
        and isinstance(function.returns, ast.Constant)
        and function.returns.value is None
    )


def _dump_nodes(nodes: Sequence[ast.expr | None]) -> list[str | None]:
    return [None if node is None else ast.dump(node) for node in nodes]


def test_extracted_server_runner_helpers_are_thin_wrappers() -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_runners" in bound_helpers:
        assert set(EXTRACTED_SERVER_RUNNER_HELPERS) <= set(
            bound_helpers["_server_runners"]
        )
        for helper_name in EXTRACTED_SERVER_RUNNER_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    _, functions = _read_module_ast(server)
    _, runner_functions = _read_module_ast(server_runners)

    for helper_name in EXTRACTED_SERVER_RUNNER_HELPERS:
        function = functions.get(helper_name)
        runner_function = runner_functions.get(helper_name)
        assert function is not None, f"Missing wrapper for {helper_name}"
        assert runner_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )
        assert _dump_nodes(function.args.defaults) == _dump_nodes(
            runner_function.args.defaults
        )
        assert _dump_nodes(function.args.kw_defaults) == _dump_nodes(
            runner_function.args.kw_defaults
        )

        statement = function.body[0]
        if _returns_none(function):
            assert isinstance(statement, ast.Expr)
        else:
            assert isinstance(statement, ast.Return)

        call = statement.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "_server_runners"
        assert call.func.attr == helper_name
        assert call.args, f"{helper_name} should pass the server module first"
        assert _is_server_module_reference(call.args[0])

        positional_parameter_names = _positional_parameter_names(function)
        assert len(call.args[1:]) == len(positional_parameter_names)
        for argument, parameter_name in zip(
            call.args[1:], positional_parameter_names, strict=True
        ):
            assert isinstance(argument, ast.Name)
            assert argument.id == parameter_name

        kwonly_keywords = [
            keyword for keyword in call.keywords if keyword.arg is not None
        ]
        assert len(kwonly_keywords) == len(function.args.kwonlyargs)
        for keyword, parameter in zip(
            kwonly_keywords, function.args.kwonlyargs, strict=True
        ):
            assert keyword.arg == parameter.arg
            assert isinstance(keyword.value, ast.Name)
            assert keyword.value.id == parameter.arg

        kwarg_keywords = [keyword for keyword in call.keywords if keyword.arg is None]
        if function.args.kwarg is not None:
            assert len(kwarg_keywords) == 1
            assert isinstance(kwarg_keywords[0].value, ast.Name)
            assert kwarg_keywords[0].value.id == function.args.kwarg.arg
        else:
            assert not kwarg_keywords


def test_build_runner_status_payload_uses_server_indirection(monkeypatch) -> None:
    sentinel_availability = {
        "available_runners": ["codex"],
        "supported_runners": ["claude", "codex"],
        "claude_code_available": True,
    }
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: sentinel_availability,
    )

    payload = server._build_runner_status_payload()

    assert payload["available_runners"] == sentinel_availability["available_runners"]
    assert payload["supported_runners"] == sentinel_availability["supported_runners"]
    assert (
        payload["claude_code_available"]
        is sentinel_availability["claude_code_available"]
    )


def test_runner_auth_launch_command_uses_server_indirection(monkeypatch) -> None:
    monkeypatch.setattr(
        server, "_runner_auth_launch_parts", lambda runner: [runner, "login"]
    )

    assert server._runner_auth_launch_command("codex") == "codex login"


def test_read_url_bytes_uses_server_urllib_request_indirection(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return b"sentinel-bytes"

    class ServerUrlLibRequestStub:
        @staticmethod
        def Request(url, headers=None):
            return {"url": url, "headers": headers}

        @staticmethod
        def urlopen(request, timeout=60):
            assert request["url"] == "https://example.com/test"
            assert request["headers"] == {"User-Agent": "OpenPlot"}
            assert timeout == 60
            return DummyResponse()

    class ExtractedModuleUrlLibRequestFailFastStub:
        @staticmethod
        def Request(url, headers=None):
            raise AssertionError("server_runners urllib_request should not be used")

        @staticmethod
        def urlopen(request, timeout=60):
            raise AssertionError("server_runners urllib_request should not be used")

    monkeypatch.setattr(server, "urllib_request", ServerUrlLibRequestStub)
    monkeypatch.setattr(
        server_runners,
        "urllib_request",
        ExtractedModuleUrlLibRequestFailFastStub,
    )

    assert server._read_url_bytes("https://example.com/test") == b"sentinel-bytes"

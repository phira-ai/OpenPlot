from pathlib import Path

from openplot import desktop
import openplot.server as server


def test_desktop_dropped_file_paths_filters_invalid_entries() -> None:
    event = {
        "dataTransfer": {
            "files": [
                {"pywebviewFullPath": " /tmp/report.csv "},
                {"pywebviewFullPath": ""},
                {"name": "missing-path"},
                {"pywebviewFullPath": "/tmp/report.csv"},
                {"pywebviewFullPath": "/tmp/plot.py"},
            ]
        }
    }

    assert desktop._desktop_dropped_file_paths(event) == [
        "/tmp/report.csv",
        "/tmp/plot.py",
    ]


def test_desktop_file_drop_script_includes_event_name_and_paths() -> None:
    script = desktop._desktop_file_drop_script(["/tmp/report.csv", "/tmp/plot.py"])

    assert "openplot-desktop-file-drop" in script
    assert '"/tmp/report.csv"' in script
    assert '"/tmp/plot.py"' in script


def test_desktop_no_file_startup_uses_home(monkeypatch, tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    workspace_calls: list[Path] = []
    written_ports: list[int] = []

    class _EventHook:
        def __init__(self) -> None:
            self.handlers: list[object] = []

        def __iadd__(self, handler: object):
            self.handlers.append(handler)
            return self

    class _Window:
        def __init__(self) -> None:
            self.events = type("Events", (), {"closed": _EventHook()})()

    created_urls: list[str] = []
    fake_window = _Window()

    class _FakeServer:
        def __init__(self, _config) -> None:
            self.started = False
            self.should_exit = False

        def run(self) -> None:
            self.started = True

    class _FakeWebview:
        @staticmethod
        def create_window(*_args, **kwargs):
            created_urls.append(kwargs["url"])
            return fake_window

        @staticmethod
        def start(*_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(desktop.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.setattr(desktop.importlib, "import_module", lambda name: _FakeWebview)
    monkeypatch.setattr(
        desktop,
        "set_runtime_workspace_dir",
        lambda _runtime, path: workspace_calls.append(Path(path)),
    )
    monkeypatch.setattr(
        desktop,
        "write_runtime_port_file",
        lambda _runtime, port: written_ports.append(port),
    )
    monkeypatch.setattr(server, "create_app", lambda: object())
    monkeypatch.setattr(desktop, "_pick_free_port", lambda: 17625)
    monkeypatch.setattr(desktop.uvicorn, "Server", _FakeServer)
    monkeypatch.setattr(
        desktop.uvicorn, "Config", lambda app, **kwargs: {"app": app, **kwargs}
    )

    desktop.launch_desktop(None, host="127.0.0.1", port=0)

    assert workspace_calls == [home_dir]
    assert written_ports == [17625]
    assert created_urls == ["http://127.0.0.1:17625"]

from openplot import desktop


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

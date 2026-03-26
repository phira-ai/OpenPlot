from __future__ import annotations

import pytest
from urllib.request import Request

import openplot.mcp_server as mcp_server


def test_request_json_wraps_undecodable_success_response(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b"\x8c"

    monkeypatch.setattr(
        mcp_server, "urlopen", lambda *_args, **_kwargs: DummyResponse()
    )

    with pytest.raises(mcp_server.BackendError, match="Invalid JSON"):
        mcp_server._request_json(
            Request("http://127.0.0.1:17623/api/test"), timeout_s=1.0
        )

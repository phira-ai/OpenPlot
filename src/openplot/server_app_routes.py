"""App route registration helpers extracted from openplot.server."""

from __future__ import annotations

from types import ModuleType

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def _register_routes(server_module: ModuleType, app: FastAPI) -> None:
    from .api.annotations import router as annotations_router
    from .api.artifacts import router as artifacts_router
    from .api.fix_jobs import router as fix_jobs_router
    from .api.plot_mode import router as plot_mode_router
    from .api.preferences import router as preferences_router
    from .api.runners import router as runners_router
    from .api.runtime import router as runtime_router
    from .api.sessions import router as sessions_router
    from .api.versioning import router as versioning_router
    from .api.ws import router as ws_router

    @app.get("/", response_class=HTMLResponse)
    async def index():
        static_dir = server_module._resolve_static_dir()
        index_file = static_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(server_module._read_file_text(index_file))
        return HTMLResponse(
            "<html><body>"
            "<h1>OpenPlot</h1>"
            "<p>Frontend assets are missing.</p>"
            "<p>If running from source, run <code>npm run build --prefix frontend</code>.</p>"
            "<p>If installed from a package, reinstall a build that includes <code>openplot/static</code>.</p>"
            "</body></html>"
        )

    app.include_router(sessions_router)
    app.include_router(plot_mode_router)
    app.include_router(annotations_router)
    app.include_router(fix_jobs_router)
    app.include_router(runners_router)
    app.include_router(preferences_router)
    app.include_router(artifacts_router)
    app.include_router(versioning_router)
    app.include_router(runtime_router)
    app.include_router(ws_router)

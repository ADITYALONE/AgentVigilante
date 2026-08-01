"""FastAPI application: command proxy + local approval dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_jail.core import proxy as proxy_module
from agent_jail.core.diff_engine import DiffEngine
from agent_jail.core.egress_proxy import WhitelistProxy
from agent_jail.core.isolation import AgentSandbox, DEFAULT_BASE_IMAGE
from agent_jail.core.proxy import router as proxy_router

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app(
    workdir: str | Path,
    base_image: str = DEFAULT_BASE_IMAGE,
    proxy_port: int = 8888,
    *,
    notify_url: str = "http://127.0.0.1:8420",
    native_notify: bool = True,
    autopilot: bool = False,
    mode: str = "interactive",
) -> FastAPI:
    """Build the AgentJail ASGI app with sandbox, egress proxy, and dashboard."""
    workdir_path = Path(workdir).resolve()
    workdir_path.mkdir(parents=True, exist_ok=True)

    sandbox = AgentSandbox(
        workdir=workdir_path,
        base_image=base_image,
        proxy_port=proxy_port,
    )
    diff_engine = DiffEngine(root=workdir_path)
    egress = WhitelistProxy(host="0.0.0.0", port=proxy_port)
    proxy_module.configure(
        sandbox,
        diff_engine,
        egress,
        autopilot=autopilot,
        mode=mode,
    )

    from agent_jail.notify import configure_notify

    configure_notify(base_url=notify_url, enabled=native_notify)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = await egress.start_background()
        app.state.egress_proxy = egress
        app.state.egress_task = task
        logger.info("Egress proxy listening on 0.0.0.0:%s", proxy_port)
        try:
            yield
        finally:
            await egress.stop()

    app = FastAPI(
        title="AgentJail",
        description="Local human-in-the-loop sandboxing proxy for AI agents",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.include_router(proxy_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if WEB_DIST.is_dir() and (WEB_DIST / "index.html").is_file():
        assets = WEB_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def spa_index() -> FileResponse:
            return FileResponse(WEB_DIST / "index.html")

        # Serve other static files from dist (favicon, lego-front.jpg, etc.)
        @app.get("/{path:path}")
        async def spa_assets(path: str) -> FileResponse:
            candidate = WEB_DIST / path
            if candidate.is_file() and WEB_DIST in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

        logger.info("Serving shadcn dashboard from %s", WEB_DIST)
    else:
        from fastapi import Request
        from fastapi.responses import HTMLResponse
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(
            directory=str(Path(__file__).resolve().parent / "templates")
        )

        @app.get("/", response_class=HTMLResponse)
        async def legacy_dashboard(request: Request) -> HTMLResponse:
            return templates.TemplateResponse(
                request,
                "index.html",
                {"title": "AgentJail"},
            )

        logger.warning(
            "web/dist missing — falling back to Jinja dashboard. "
            "Run: cd web && npm run build"
        )

    logger.info(
        "AgentJail app created workdir=%s image=%s proxy_port=%s",
        workdir_path,
        base_image,
        proxy_port,
    )
    return app

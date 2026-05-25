from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from architect.core.config import get_settings
from architect.core.database import dispose_engine, get_engine
from architect.core.observability import configure_logging
from architect.runtime.dispatcher import Dispatcher

# Module-level dispatcher registry, keyed by workflow slug.
# Populated at app creation time, read by approval tools at request time.
_dispatchers: dict[str, Dispatcher] = {}


def get_dispatcher(workflow_slug: str) -> Dispatcher | None:
    """Get the Dispatcher for a given workflow slug (if any)."""
    return _dispatchers.get(workflow_slug)


def _build_mcp_app(workflow_slug: str, register_fn: Any) -> Starlette:
    """Build an MCP sub-app for a single workflow."""
    mcp = FastMCP(
        f"The Architect — {workflow_slug}",
        stateless_http=True,
        streamable_http_path="/",
    )
    register_fn(mcp)
    return mcp.streamable_http_app()


def create_app(
    workflow_modules: list[dict[str, Any]] | None = None,
    dispatchers: dict[str, Dispatcher] | None = None,
) -> FastAPI:
    """Create the FastAPI app with MCP sub-apps for each workflow.

    workflow_modules: list of dicts with keys:
        - slug: str
        - register_fn: callable that takes FastMCP and registers tools
    dispatchers: dict mapping workflow_slug -> Dispatcher instance
    """
    settings = get_settings()
    mcp_apps: dict[str, Starlette] = {}

    # Store dispatchers in module-level registry for access by approval tools
    if dispatchers:
        _dispatchers.update(dispatchers)

    if workflow_modules:
        for wf in workflow_modules:
            mcp_apps[wf["slug"]] = _build_mcp_app(wf["slug"], wf["register_fn"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        get_engine()
        # Delegate lifespan to MCP sub-apps
        contexts = []
        for mcp_app in mcp_apps.values():
            ctx = mcp_app.router.lifespan_context(app)
            await ctx.__aenter__()
            contexts.append(ctx)
        yield
        for ctx in reversed(contexts):
            await ctx.__aexit__(None, None, None)
        await dispose_engine()

    app = FastAPI(
        title="The Architect",
        version="0.0.1",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "workflows": list(mcp_apps.keys()),
            "dispatchers": list(_dispatchers.keys()),
        }

    for slug, mcp_app in mcp_apps.items():
        app.mount(f"{settings.mcp_path}/{slug}", mcp_app)

    return app

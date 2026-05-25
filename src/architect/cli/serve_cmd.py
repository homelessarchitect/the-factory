from __future__ import annotations

import asyncio
import importlib

import click


def _load_applied_workflows() -> list[dict]:
    """Load all applied workflows from the state table.

    For each workflow, loads:
    - Generated CRUD + pipeline tools (register_fn)
    - Dispatcher definitions (from state.entities.dispatchers)
    """
    import sys
    from pathlib import Path

    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    from architect.core.database import get_session_factory, reset_engine
    from architect.modules.state.service import StateService

    async def _fetch():
        factory = get_session_factory()
        async with factory() as session:
            svc = StateService(session)
            states = await svc.list_all_latest()
            return states

    states = asyncio.run(_fetch())
    reset_engine()

    modules = []
    for state in states:
        slug = state.workflow_slug
        module_path = f"architect.generated.{slug}._tools_registry"
        try:
            # Import models so they're registered with Base.metadata for DB access
            entity_names = state.entities.get("names", []) if state.entities else []
            for entity_name in entity_names:
                try:
                    importlib.import_module(f"architect.generated.{slug}.{entity_name}.models")
                except ModuleNotFoundError:
                    pass

            mod = importlib.import_module(module_path)

            # Extract dispatcher definitions from state
            dispatcher_defs = []
            if state.entities:
                dispatcher_defs = state.entities.get("dispatchers", [])

            modules.append({
                "slug": slug,
                "register_fn": mod.register_all_tools,
                "dispatcher_defs": dispatcher_defs,
            })
            click.echo(
                f"  Loaded workflow: {slug} "
                f"(v{state.version}, {state.tools_count} tools"
                f"{', ' + str(len(dispatcher_defs)) + ' dispatchers' if dispatcher_defs else ''})"
            )
        except ModuleNotFoundError:
            click.echo(f"  WARNING: Generated code for '{slug}' not found. Run `architect apply` first.")
    return modules


def _build_dispatchers(workflow_modules: list[dict]) -> dict:
    """Build Dispatcher instances per workflow slug from stored definitions.

    Returns a dict mapping workflow_slug -> Dispatcher.
    """
    from architect.primitives.dispatcher import DispatcherDefinition
    from architect.runtime.dispatcher import Dispatcher

    dispatchers = {}
    for wf in workflow_modules:
        defs = wf.get("dispatcher_defs", [])
        if not defs:
            continue

        definitions = [
            DispatcherDefinition(
                action_type=d["action_type"],
                handler=d.get("handler", ""),
                provider=d.get("provider", ""),
                provider_action=d.get("provider_action", ""),
            )
            for d in defs
        ]
        dispatchers[wf["slug"]] = Dispatcher(definitions)

    return dispatchers


@click.command("serve")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", "-p", default=8000, type=int, help="Port to bind to")
def serve_cmd(host: str, port: int) -> None:
    """Start the FastAPI server with all applied workflows."""
    import uvicorn

    click.echo(f"Starting The Architect on {host}:{port}...")
    click.echo("Loading workflows from state...")

    from architect.runtime.app import create_app

    workflow_modules = _load_applied_workflows()
    if not workflow_modules:
        click.echo("  No workflows found. Run `architect apply <workflow.py>` first.\n")

    dispatchers = _build_dispatchers(workflow_modules)
    if dispatchers:
        click.echo(f"  Dispatchers wired: {', '.join(dispatchers.keys())}")

    app = create_app(workflow_modules, dispatchers=dispatchers)
    click.echo("")
    uvicorn.run(app, host=host, port=port)

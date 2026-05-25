"""architect apply — generate code, run migrations, and update state."""

from __future__ import annotations

import asyncio
import importlib

import click

from architect.cli.loader import load_workflow_from_file
from architect.core.database import Base, dispose_engine, get_engine, get_session_factory
from architect.modules.state.service import StateService


@click.command("apply")
@click.argument("workflow_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force re-generation even if no changes detected.")
def apply_cmd(workflow_path: str, force: bool) -> None:
    """Generate code, run migrations, and update state."""
    asyncio.run(_apply(workflow_path, force=force))


async def _apply(workflow_path: str, *, force: bool = False) -> None:
    workflow = load_workflow_from_file(workflow_path)
    current_hash = StateService.compute_hash(workflow_path)
    entity_names = [e.name for e in workflow.entities]

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = get_session_factory()
    async with factory() as session:
        service = StateService(session)

        # Check if anything changed
        diff = await service.diff_state(workflow.slug, current_hash, entity_names)
        if diff["status"] == "no_changes" and not force:
            click.echo("Nothing to apply -- no changes detected.")
            await dispose_engine()
            return

        # Acquire lock
        lock = await service.acquire_lock(workflow.slug, "apply")
        await session.commit()

        try:
            # Generate code
            click.echo("Generating models...     ", nl=False)
            from architect.generators.orchestrator import generate_workflow

            generate_workflow(workflow)
            click.echo("done")

            # Count generated artefacts
            entity_count = len(workflow.entities)
            tools_count = entity_count * 5

            click.echo(f"Generating schemas...    done  {entity_count} entities")
            click.echo(f"Generating tools...      done  {tools_count} CRUD tools")

            # Import generated models and built-in modules, then create all tables
            click.echo("Creating tables...       ", nl=False)
            import architect.modules.approvals.models  # noqa: F401
            import architect.modules.api_keys.models  # noqa: F401
            import architect.modules.budgets.models  # noqa: F401
            import architect.modules.credentials.models  # noqa: F401
            import architect.modules.executions.models  # noqa: F401
            for entity_name in entity_names:
                try:
                    importlib.import_module(
                        f"architect.generated.{workflow.slug}.{entity_name}.models"
                    )
                except ModuleNotFoundError:
                    pass
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            click.echo("done")

            # Create new state version
            tables = [e.table_name for e in workflow.entities]
            providers = (
                [p.name if hasattr(p, "name") else str(p) for p in workflow.providers]
                if workflow.providers
                else []
            )

            # Store dispatcher definitions for serve-time reconstruction
            dispatcher_defs = [
                {
                    "action_type": d.action_type,
                    "handler": d.handler,
                    "provider": d.provider,
                    "provider_action": d.provider_action,
                }
                for d in workflow.dispatchers
            ]

            # Store pipeline count for tools_count
            pipeline_tool_count = len(workflow.pipelines)

            state = await service.create_version(
                workflow_slug=workflow.slug,
                schema_hash=current_hash,
                entities={
                    "names": entity_names,
                    "dispatchers": dispatcher_defs,
                },
                tools_count=tools_count + pipeline_tool_count,
                tables_list=tables,
                providers=providers,
            )
            await session.commit()
            click.echo(f"Updating state...        done  v{state.version}")
            click.echo(
                "\n  Applied successfully. Run `architect serve` to start.\n"
            )
        finally:
            await service.release_lock(workflow.slug, lock.lock_id)
            await session.commit()

    await dispose_engine()

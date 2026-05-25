"""Pipeline tool generator — produces transition MCP tools from PipelineDefinitions."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from architect.primitives.pipeline import PipelineDefinition

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_pipeline_tools(
    pipelines: list[PipelineDefinition],
    workflow_slug: str,
    output_dir: Path,
) -> Path | None:
    """Generate a ``_pipeline_tools.py`` file with transition tools for all pipelines.

    Returns the output path, or ``None`` if there are no pipelines.
    """
    if not pipelines:
        return None

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("pipeline_tool.py.j2")

    content = template.render(
        pipelines=pipelines,
        workflow_slug=workflow_slug,
    )

    output_path = output_dir / "_pipeline_tools.py"
    output_path.write_text(content)
    return output_path

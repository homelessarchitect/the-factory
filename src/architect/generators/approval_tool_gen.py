"""Approval tool generator — produces approve/reject/list MCP tools."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_approval_tools(
    workflow_slug: str,
    output_dir: Path,
) -> Path:
    """Generate ``_approval_tools.py`` with approve, reject, and list_pending tools."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("approval_tool.py.j2")

    content = template.render(workflow_slug=workflow_slug)

    output_path = output_dir / "_approval_tools.py"
    output_path.write_text(content)
    return output_path

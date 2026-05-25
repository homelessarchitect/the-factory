"""Tests for pipeline tool generation and the generated transition tools."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import pytest

from architect.generators.orchestrator import generate_workflow
from architect.generators.pipeline_tool_gen import generate_pipeline_tools
from architect.primitives import (
    EntityDefinition,
    FieldDef,
    PipelineDefinition,
    ToolDefinition,
    Transition,
    WorkflowDefinition,
)


class PieceStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AssetStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    READY = "ready"


@pytest.fixture
def piece_pipeline() -> PipelineDefinition:
    return PipelineDefinition(
        entity_name="content_piece",
        statuses=["draft", "review", "published", "archived"],
        transitions=[
            Transition("draft", "review"),
            Transition(
                "review",
                "published",
                approval_required=True,
                approval_action_type="publish_piece",
            ),
            Transition("published", "archived"),
            Transition("review", "draft"),
        ],
    )


@pytest.fixture
def asset_pipeline() -> PipelineDefinition:
    return PipelineDefinition(
        entity_name="asset",
        statuses=["pending", "in-progress", "ready"],
        transitions=[
            Transition("pending", "in-progress"),
            Transition("in-progress", "ready"),
        ],
    )


@pytest.fixture
def workflow_with_pipelines(piece_pipeline, asset_pipeline) -> WorkflowDefinition:
    content_piece = EntityDefinition(
        name="content_piece",
        fields=[
            FieldDef("title", str, max_length=255),
            FieldDef("status", PieceStatus, default=PieceStatus.DRAFT),
        ],
    )
    asset = EntityDefinition(
        name="asset",
        fields=[
            FieldDef("name", str, max_length=255),
            FieldDef("status", AssetStatus, default=AssetStatus.PENDING),
        ],
    )
    return WorkflowDefinition(
        name="Test Content",
        slug="testcontent",
        entities=[content_piece, asset],
        pipelines=[piece_pipeline, asset_pipeline],
        tools=[
            ToolDefinition.crud("content_piece"),
            ToolDefinition.crud("asset"),
        ],
    )


@pytest.fixture
def workflow_no_pipelines() -> WorkflowDefinition:
    item = EntityDefinition(
        name="item",
        fields=[FieldDef("name", str, max_length=255)],
    )
    return WorkflowDefinition(
        name="Simple",
        slug="simple",
        entities=[item],
        tools=[ToolDefinition.crud("item")],
    )


class TestPipelineToolGeneration:
    def test_generates_pipeline_tools_file(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        assert result is not None
        assert result.exists()
        assert result.name == "_pipeline_tools.py"

    def test_returns_none_for_empty_pipelines(self, tmp_path):
        result = generate_pipeline_tools([], "test", tmp_path)
        assert result is None

    def test_generated_file_is_valid_python(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        compile(content, str(result), "exec")

    def test_generated_file_has_auto_header(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "AUTO-GENERATED" in content

    def test_contains_transition_function(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "transition_content_piece_status" in content

    def test_contains_pipeline_data(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "_PIPELINE_TRANSITIONS" in content
        assert '"content_piece"' in content
        assert '"draft"' in content
        assert '"review"' in content
        assert '"published"' in content

    def test_contains_approval_data(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert '"approval_required": True' in content
        assert '"publish_piece"' in content

    def test_multiple_pipelines_generate_multiple_tools(
        self, piece_pipeline, asset_pipeline, tmp_path,
    ):
        result = generate_pipeline_tools(
            [piece_pipeline, asset_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "transition_content_piece_status" in content
        assert "transition_asset_status" in content

    def test_contains_validate_function(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "_validate_transition" in content

    def test_contains_register_function(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "def register(mcp:" in content

    def test_references_correct_repository(self, piece_pipeline, tmp_path):
        result = generate_pipeline_tools(
            [piece_pipeline], "testcontent", tmp_path,
        )
        content = result.read_text()
        assert "ContentPieceRepository" in content
        assert "architect.generated.testcontent.content_piece.repository" in content


class TestOrchestratorWithPipelines:
    def test_generates_pipeline_tools_file(self, workflow_with_pipelines, tmp_path):
        generate_workflow(workflow_with_pipelines, tmp_path)
        pipeline_file = tmp_path / "testcontent" / "_pipeline_tools.py"
        assert pipeline_file.exists()

    def test_tools_registry_includes_pipelines(self, workflow_with_pipelines, tmp_path):
        generate_workflow(workflow_with_pipelines, tmp_path)
        registry = tmp_path / "testcontent" / "_tools_registry.py"
        content = registry.read_text()
        assert "register_pipelines" in content
        assert "_pipeline_tools" in content

    def test_no_pipeline_tools_when_no_pipelines(self, workflow_no_pipelines, tmp_path):
        generate_workflow(workflow_no_pipelines, tmp_path)
        pipeline_file = tmp_path / "simple" / "_pipeline_tools.py"
        assert not pipeline_file.exists()

    def test_tools_registry_omits_pipelines_when_none(self, workflow_no_pipelines, tmp_path):
        generate_workflow(workflow_no_pipelines, tmp_path)
        registry = tmp_path / "simple" / "_tools_registry.py"
        content = registry.read_text()
        assert "register_pipelines" not in content

    def test_all_generated_files_valid_python(self, workflow_with_pipelines, tmp_path):
        generate_workflow(workflow_with_pipelines, tmp_path)
        for py_file in (tmp_path / "testcontent").rglob("*.py"):
            content = py_file.read_text()
            compile(content, str(py_file), "exec")


class TestValidateTransitionLogic:
    """Test the _validate_transition function by executing the generated code."""

    def _load_validate(self, pipelines, slug, tmp_path):
        """Generate pipeline tools and return the _validate_transition function."""
        generate_pipeline_tools(pipelines, slug, tmp_path)
        code = (tmp_path / "_pipeline_tools.py").read_text()
        namespace = {}
        exec(code, namespace)
        return namespace["_validate_transition"]

    def test_valid_transition(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "draft", "review")
        assert result["allowed"] is True

    def test_invalid_transition(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "draft", "published")
        assert result["allowed"] is False
        assert "allowed_transitions" in result

    def test_approval_required(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "review", "published")
        assert result["allowed"] is True
        assert result["approval_required"] is True
        assert result["approval_action_type"] == "publish_piece"

    def test_invalid_from_status(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "nonexistent", "review")
        assert result["allowed"] is False

    def test_invalid_to_status(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "draft", "nonexistent")
        assert result["allowed"] is False

    def test_no_transitions_from_terminal(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "archived", "draft")
        assert result["allowed"] is False
        assert result["allowed_transitions"] == []

    def test_unknown_entity_passes(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("unknown", "any", "thing")
        assert result["allowed"] is True

    def test_reverse_transition(self, piece_pipeline, tmp_path):
        validate = self._load_validate([piece_pipeline], "test", tmp_path)
        result = validate("content_piece", "review", "draft")
        assert result["allowed"] is True
        assert result.get("approval_required") is not True

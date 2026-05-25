"""Tests for approval tool generation and dispatcher wiring."""

from __future__ import annotations

from enum import StrEnum

import pytest

from architect.generators.approval_tool_gen import generate_approval_tools
from architect.generators.orchestrator import generate_workflow
from architect.primitives import (
    DispatcherDefinition,
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


@pytest.fixture
def workflow_with_dispatchers() -> WorkflowDefinition:
    piece = EntityDefinition(
        name="content_piece",
        fields=[
            FieldDef("title", str, max_length=255),
            FieldDef("status", PieceStatus, default=PieceStatus.DRAFT),
        ],
    )
    return WorkflowDefinition(
        name="Test Content",
        slug="testcontent",
        entities=[piece],
        pipelines=[
            PipelineDefinition(
                entity_name="content_piece",
                statuses=["draft", "review", "published"],
                transitions=[
                    Transition("draft", "review"),
                    Transition(
                        "review",
                        "published",
                        approval_required=True,
                        approval_action_type="publish_piece",
                    ),
                ],
            ),
        ],
        dispatchers=[
            DispatcherDefinition(
                action_type="publish_piece",
                handler="some.module.execute_publish",
            ),
        ],
        tools=[ToolDefinition.crud("content_piece")],
    )


@pytest.fixture
def workflow_no_dispatchers() -> WorkflowDefinition:
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


class TestApprovalToolGeneration:
    def test_generates_approval_tools_file(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        assert result.exists()
        assert result.name == "_approval_tools.py"

    def test_generated_file_is_valid_python(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        content = result.read_text()
        compile(content, str(result), "exec")

    def test_generated_file_has_auto_header(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        content = result.read_text()
        assert "AUTO-GENERATED" in content

    def test_contains_approve_function(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        content = result.read_text()
        assert "approve_approval" in content

    def test_contains_reject_function(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        content = result.read_text()
        assert "reject_approval" in content

    def test_contains_list_pending_function(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        content = result.read_text()
        assert "list_pending_approvals" in content

    def test_references_get_dispatcher(self, tmp_path):
        result = generate_approval_tools("testcontent", tmp_path)
        content = result.read_text()
        assert "get_dispatcher" in content

    def test_uses_correct_workflow_slug(self, tmp_path):
        result = generate_approval_tools("myworkflow", tmp_path)
        content = result.read_text()
        assert "myworkflow" in content


class TestOrchestratorWithApprovals:
    def test_generates_approval_tools_with_dispatchers(
        self, workflow_with_dispatchers, tmp_path,
    ):
        generate_workflow(workflow_with_dispatchers, tmp_path)
        approval_file = tmp_path / "testcontent" / "_approval_tools.py"
        assert approval_file.exists()

    def test_tools_registry_includes_approvals(
        self, workflow_with_dispatchers, tmp_path,
    ):
        generate_workflow(workflow_with_dispatchers, tmp_path)
        registry = tmp_path / "testcontent" / "_tools_registry.py"
        content = registry.read_text()
        assert "register_approvals" in content
        assert "_approval_tools" in content

    def test_no_approval_tools_when_no_dispatchers_or_gates(
        self, workflow_no_dispatchers, tmp_path,
    ):
        generate_workflow(workflow_no_dispatchers, tmp_path)
        approval_file = tmp_path / "simple" / "_approval_tools.py"
        assert not approval_file.exists()

    def test_tools_registry_omits_approvals_when_none(
        self, workflow_no_dispatchers, tmp_path,
    ):
        generate_workflow(workflow_no_dispatchers, tmp_path)
        registry = tmp_path / "simple" / "_tools_registry.py"
        content = registry.read_text()
        assert "register_approvals" not in content

    def test_all_generated_files_valid_python(
        self, workflow_with_dispatchers, tmp_path,
    ):
        generate_workflow(workflow_with_dispatchers, tmp_path)
        for py_file in (tmp_path / "testcontent").rglob("*.py"):
            content = py_file.read_text()
            compile(content, str(py_file), "exec")


class TestDispatcherWiring:
    """Test that dispatcher definitions are correctly serializable for state storage."""

    def test_dispatcher_serialization(self):
        d = DispatcherDefinition(
            action_type="publish_piece",
            handler="some.module.execute_publish",
        )
        serialized = {
            "action_type": d.action_type,
            "handler": d.handler,
            "provider": d.provider,
            "provider_action": d.provider_action,
        }
        assert serialized["action_type"] == "publish_piece"
        assert serialized["handler"] == "some.module.execute_publish"
        assert serialized["provider"] == ""
        assert serialized["provider_action"] == ""

    def test_dispatcher_deserialization(self):
        data = {
            "action_type": "publish_piece",
            "handler": "some.module.execute_publish",
            "provider": "",
            "provider_action": "",
        }
        d = DispatcherDefinition(
            action_type=data["action_type"],
            handler=data["handler"],
            provider=data["provider"],
            provider_action=data["provider_action"],
        )
        assert d.action_type == "publish_piece"
        assert d.handler == "some.module.execute_publish"

    def test_dispatcher_provider_serialization(self):
        d = DispatcherDefinition(
            action_type="send_email",
            provider="resend",
            provider_action="send",
        )
        serialized = {
            "action_type": d.action_type,
            "handler": d.handler,
            "provider": d.provider,
            "provider_action": d.provider_action,
        }
        assert serialized["provider"] == "resend"
        assert serialized["provider_action"] == "send"

    def test_build_dispatchers_from_state_data(self):
        """Test the pattern used in serve_cmd._build_dispatchers."""
        from architect.runtime.dispatcher import Dispatcher

        defs_data = [
            {
                "action_type": "publish_piece",
                "handler": "some.module.execute_publish",
                "provider": "",
                "provider_action": "",
            },
        ]
        definitions = [
            DispatcherDefinition(
                action_type=d["action_type"],
                handler=d.get("handler", ""),
                provider=d.get("provider", ""),
                provider_action=d.get("provider_action", ""),
            )
            for d in defs_data
        ]
        dispatcher = Dispatcher(definitions)
        assert "publish_piece" in dispatcher.list_action_types()


class TestAppDispatcherRegistry:
    """Test the module-level dispatcher registry in app.py."""

    def test_get_dispatcher_returns_none_when_not_set(self):
        from architect.runtime.app import get_dispatcher

        result = get_dispatcher("nonexistent")
        assert result is None

    def test_create_app_stores_dispatchers(self):
        from architect.runtime.app import _dispatchers, create_app, get_dispatcher
        from architect.runtime.dispatcher import Dispatcher

        # Clean up any previous state
        _dispatchers.clear()

        dispatcher = Dispatcher(
            [
                DispatcherDefinition(
                    action_type="test_action",
                    handler="some.module.handler",
                ),
            ]
        )

        create_app(dispatchers={"test_workflow": dispatcher})

        result = get_dispatcher("test_workflow")
        assert result is dispatcher
        assert "test_action" in result.list_action_types()

        # Cleanup
        _dispatchers.clear()

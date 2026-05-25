"""ASOS — Autonomous Sales Operating System (full port).

Complete workflow definition porting ALL ASOS entities, pipelines, custom tools,
and dispatchers to The Architect's declarative primitives.

Modules EXCLUDED (handled by The Architect core, not per-workflow):
  - api_keys        (shared auth — architect.modules.api_keys)
  - approvals       (shared HITL — architect.modules.approvals)
  - memory          (agent experience — architect.modules.state / Phase 3 pgvector)
  - outreach        (dispatcher + email — mapped as DispatcherDefinition, not an entity)

Known limitation: FieldDef.type does not support `date` (only `datetime`).
Fields like start_date, end_date, due_date use `str` with max_length to store
ISO date strings. The custom tools handle parsing.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from architect.primitives import (
    AgentDefinition,
    DispatcherDefinition,
    EntityDefinition,
    FieldDef,
    PipelineDefinition,
    ToolDefinition,
    Transition,
    WorkflowDefinition,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LeadStatus(StrEnum):
    NEW = "new"
    ENRICHED = "enriched"
    CONTACTED = "contacted"
    REPLIED = "replied"
    CONVERTED = "converted"
    REJECTED = "rejected"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class OutreachTaskStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    RESPONDED = "responded"
    NO_RESPONSE = "no_response"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Entity Definitions
# ---------------------------------------------------------------------------

# -- 1. Project (root entity — the sales playbook) -------------------------

project = EntityDefinition(
    name="project",
    fields=[
        FieldDef("name", str, required=True, max_length=255, unique=True),
        FieldDef("description", str, required=False, nullable=True),
        FieldDef(
            "icp", dict, required=False, default=dict,
            description="Ideal Customer Profile — structured for agent reasoning",
        ),
        FieldDef("value_proposition", str, required=False, nullable=True),
        FieldDef(
            "objections", list, required=False, default=list,
            description="[{trigger: str, response: str}]",
        ),
        FieldDef(
            "scoring_rubric", dict, required=False, default=dict,
            description="{high: [str], medium: [str], low: [str]}",
        ),
        FieldDef(
            "channels", list, required=False, default=list,
            description='["email", "instagram", "whatsapp"]',
        ),
        FieldDef(
            "templates", dict, required=False, default=dict,
            description="{channel_name: template_string}",
        ),
        FieldDef("is_active", bool, default=True),
    ],
    indexes=[["is_active"]],
    description="A product or service being sold, with agent-ready playbook context (ICP, scoring, objections)",
)

# -- 2. Lead (the main pipeline entity) ------------------------------------

lead = EntityDefinition(
    name="lead",
    fields=[
        FieldDef("project_id", UUID, fk="project.id", required=False, nullable=True),
        FieldDef("name", str, max_length=255, required=False, nullable=True),
        FieldDef("business_name", str, max_length=255, required=True),
        FieldDef("industry", str, max_length=100, required=False, nullable=True),
        FieldDef("website", str, max_length=500, required=False, nullable=True),
        FieldDef("instagram", str, max_length=255, required=False, nullable=True),
        FieldDef("email", str, max_length=320, required=False, nullable=True),
        FieldDef("phone", str, max_length=50, required=False, nullable=True),
        FieldDef("lead_score", int, default=0),
        FieldDef("status", LeadStatus, default=LeadStatus.NEW),
    ],
    indexes=[["status"], ["industry"], ["project_id"]],
    unique_constraints=[["instagram", "business_name"]],
    description="A sales prospect — the main pipeline entity. Deduplicated on instagram+business_name",
)

# -- 3. Interaction (audit log of agent-lead touchpoints) -------------------

interaction = EntityDefinition(
    name="interaction",
    fields=[
        FieldDef("lead_id", UUID, fk="lead.id"),
        FieldDef("agent_id", str, max_length=100, required=True),
        FieldDef(
            "channel", str, max_length=50, required=True,
            description="email | instagram_dm | whatsapp | linkedin | sms | note",
        ),
        FieldDef("message", str, required=False, nullable=True),
        FieldDef("response", str, required=False, nullable=True),
        FieldDef("timestamp", datetime),
    ],
    indexes=[["lead_id"], ["agent_id"]],
    description="Audit log of every agent-lead touchpoint (outbound + inbound)",
)

# -- 4. Campaign (time-boxed outreach effort) ------------------------------

campaign = EntityDefinition(
    name="campaign",
    fields=[
        FieldDef("project_id", UUID, fk="project.id"),
        FieldDef("name", str, max_length=255, required=True),
        FieldDef("description", str, required=False, nullable=True),
        FieldDef(
            "goal", str, required=False, nullable=True,
            description="What success looks like: '5 demos booked in Colombia Q3 2026'",
        ),
        FieldDef("target_count", int, default=0),
        FieldDef("status", CampaignStatus, default=CampaignStatus.DRAFT),
        FieldDef(
            "start_date", str, max_length=10, required=False, nullable=True,
            description="ISO date YYYY-MM-DD (stored as str, date type unsupported in FieldDef)",
        ),
        FieldDef(
            "end_date", str, max_length=10, required=False, nullable=True,
            description="ISO date YYYY-MM-DD (stored as str, date type unsupported in FieldDef)",
        ),
        FieldDef(
            "channels", list, required=False, default=list,
            description='["instagram", "whatsapp", "email"]',
        ),
        FieldDef(
            "cadence_days", list, required=False, default=list,
            description="Touchpoint schedule in days from first contact: [0, 4, 11, 21, 35]",
        ),
        FieldDef("assigned_to", str, max_length=100, default="darien"),
    ],
    indexes=[["project_id"], ["status"]],
    description="A time-boxed outreach effort for a project, with measurable goals and cadence",
)

# -- 5. Outreach Task (individual manual touchpoint) -----------------------

outreach_task = EntityDefinition(
    name="outreach_task",
    fields=[
        FieldDef("campaign_id", UUID, fk="campaign.id"),
        FieldDef("lead_id", UUID, fk="lead.id"),
        FieldDef(
            "project_id", UUID, fk="project.id", required=False, nullable=True,
            description="Denormalized from campaign -> project for fast querying without joins",
        ),
        FieldDef("assigned_to", str, max_length=100, default="darien"),
        FieldDef(
            "channel", str, max_length=50, required=True,
            description="instagram | whatsapp | email | facebook",
        ),
        FieldDef("from_account", str, max_length=255, required=False, nullable=True),
        FieldDef(
            "touch_number", int, default=1,
            description="Which touchpoint in the cadence (1=first contact, 2=follow-up, etc.)",
        ),
        FieldDef(
            "due_date", str, max_length=10, required=False, nullable=True,
            description="ISO date YYYY-MM-DD (stored as str, date type unsupported in FieldDef)",
        ),
        FieldDef("message_draft", str, required=False, nullable=True),
        FieldDef("status", OutreachTaskStatus, default=OutreachTaskStatus.PENDING),
        FieldDef("response", str, required=False, nullable=True),
        FieldDef("notes", str, required=False, nullable=True),
        FieldDef("sent_at", datetime, required=False, nullable=True),
        FieldDef("responded_at", datetime, required=False, nullable=True),
    ],
    indexes=[["campaign_id"], ["lead_id"], ["status"], ["assigned_to"], ["due_date"]],
    description="A single manual outreach touchpoint assigned to a human operator within a campaign",
)


# ---------------------------------------------------------------------------
# Pipeline Definitions (status machines with approval gates)
# ---------------------------------------------------------------------------

# Lead pipeline: new -> enriched -> contacted -> replied -> converted | rejected
# The main sales funnel with HITL gate on send_email (via approval queue)
lead_pipeline = PipelineDefinition(
    entity_name="lead",
    statuses=["new", "enriched", "contacted", "replied", "converted", "rejected"],
    transitions=[
        Transition("new", "enriched"),
        Transition("enriched", "contacted"),
        Transition("contacted", "replied"),
        Transition("replied", "converted"),
        # Direct jumps (e.g. first contact without enrichment)
        Transition("new", "contacted"),
        # Rejection from any active status
        Transition("new", "rejected"),
        Transition("enriched", "rejected"),
        Transition("contacted", "rejected"),
        Transition("replied", "rejected"),
    ],
    initial_status="new",
)

# Campaign pipeline: draft -> active -> paused -> completed -> archived
campaign_pipeline = PipelineDefinition(
    entity_name="campaign",
    statuses=["draft", "active", "paused", "completed", "archived"],
    transitions=[
        Transition("draft", "active"),
        Transition("active", "paused"),
        Transition("paused", "active"),
        Transition("active", "completed"),
        Transition("paused", "completed"),
        Transition("completed", "archived"),
    ],
    initial_status="draft",
)

# OutreachTask pipeline: pending -> sent -> responded | no_response | skipped
outreach_task_pipeline = PipelineDefinition(
    entity_name="outreach_task",
    statuses=["pending", "sent", "responded", "no_response", "skipped"],
    transitions=[
        Transition("pending", "sent"),
        Transition("pending", "skipped"),
        Transition("sent", "responded"),
        Transition("sent", "no_response"),
    ],
    initial_status="pending",
)


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------
# CRUD tools are auto-generated. Custom tools need ToolDefinition.custom().
# Custom tools are domain-specific logic that goes beyond simple CRUD.
# Their dotpath points to the module where register(mcp) lives.

tools = [
    # -- CRUD for all entities --
    ToolDefinition.crud("project"),
    ToolDefinition.crud("lead"),
    ToolDefinition.crud("interaction"),
    ToolDefinition.crud("campaign"),
    ToolDefinition.crud("outreach_task"),
    # -- Custom: Agent Context --
    ToolDefinition.custom(
        "examples.asos.custom_tools.context",
        description=(
            "get_agent_context: one-shot cold-start snapshot -- active projects, "
            "pending outreach tasks, pending approvals, active campaigns, pipeline stats. "
            "get_pipeline_stats: aggregate lead funnel metrics (counts by status, avg score, stale count)"
        ),
    ),
    # -- Custom: Lead Scoring --
    ToolDefinition.custom(
        "examples.asos.custom_tools.scoring",
        description=(
            "score_lead: context-fetcher that returns lead profile + project scoring rubric "
            "for Claude to reason and assign a score; "
            "update_lead_score: persist the computed score (0-100)"
        ),
    ),
    # -- Custom: Lead Search (compound filters) --
    ToolDefinition.custom(
        "examples.asos.custom_tools.search",
        description=(
            "search_leads: compound-filter search (status_list, score range, "
            "days_since_contact, industry, project_id) -- all combined with AND"
        ),
    ),
    # -- Custom: Bulk Operations --
    ToolDefinition.custom(
        "examples.asos.custom_tools.bulk",
        description=(
            "bulk_create_leads: batch-import leads with deduplication on instagram handle; "
            "returns created/duplicate/error counts"
        ),
    ),
    # -- Custom: Approvals (HITL send_email, delete_lead) --
    ToolDefinition.custom(
        "examples.asos.custom_tools.approvals",
        description=(
            "request_send_email: queue an email to a lead for human approval (HITL gate); "
            "request_delete_lead: queue a lead deletion for human review; "
            "list_pending_approvals: check approval queue status"
        ),
    ),
    # -- Custom: Project Context --
    ToolDefinition.custom(
        "examples.asos.custom_tools.projects",
        description=(
            "list_projects_context: compact project listing with ICP + scoring rubric "
            "for agent reasoning when assigning leads to projects; "
            "get_campaign_stats: campaign-level metrics with task counts by status"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Dispatcher Definitions (execute approved HITL actions)
# ---------------------------------------------------------------------------

dispatchers = [
    # Send email to lead via Resend (after human approval)
    DispatcherDefinition(
        action_type="send_email",
        handler="examples.asos.dispatchers.execute_send_email",
    ),
    # Delete a lead (after human approval)
    DispatcherDefinition(
        action_type="delete_lead",
        handler="examples.asos.dispatchers.execute_delete_lead",
    ),
]


# ---------------------------------------------------------------------------
# Agent Configuration
# ---------------------------------------------------------------------------

agent = AgentDefinition(
    memory=True,
    experience_capture=["observation", "decision", "outcome", "pattern"],
    description=(
        "Sales operations agent for ASOS. Manages the full outreach loop: "
        "project setup -> lead enrichment -> scoring -> campaign creation -> "
        "outreach task drafting -> HITL send -> response tracking -> conversion. "
        "Deduplication on instagram+business_name is automatic."
    ),
)


# ---------------------------------------------------------------------------
# Workflow Definition (the single export)
# ---------------------------------------------------------------------------

workflow = WorkflowDefinition(
    name="ASOS Sales Ops",
    slug="asos",
    entities=[
        project,
        lead,
        interaction,
        campaign,
        outreach_task,
    ],
    pipelines=[
        lead_pipeline,
        campaign_pipeline,
        outreach_task_pipeline,
    ],
    tools=tools,
    dispatchers=dispatchers,
    agent=agent,
    description=(
        "Autonomous Sales Operating System -- agent-first CRM. "
        "Claude Code reasons, scores, and drafts outreach. The backend persists. "
        "HITL before any email send or lead deletion. "
        "Cadence-driven campaigns with manual touchpoints."
    ),
)

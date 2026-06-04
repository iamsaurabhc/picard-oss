from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowType = Literal["assistant", "tabular", "lightflow"]
WorkflowProfile = Literal["firm", "court", "any"]
WorkflowSource = Literal["builtin", "user", "agent_authored"]


class LightFlowStepDef(BaseModel):
    name: str = Field(min_length=1)
    role: str
    depends_on: list[str] = Field(default_factory=list)
    max_retry: int | None = None
    query: str | dict[str, Any] | None = None
    refuse_on_empty: bool | None = None
    evidence_tier: Literal["A", "B", "C", "D"] | None = None
    cite_from_steps: list[str] | None = None
    output_format: str | None = None
    config: dict[str, Any] | None = None


class FlowJson(BaseModel):
    version: Literal["0.8"] = "0.8"
    input_hint: str | None = None
    steps: list[LightFlowStepDef] = Field(min_length=1)


class EvidenceProfile(BaseModel):
    requires_corpus: bool = True
    allowed_intents: list[str] | None = None
    allows_tabular: bool = False
    allows_csv: bool = False
    allows_web: bool = False
    denied_roles: list[str] | None = None


class WorkflowPayload(BaseModel):
    """Create/update body for custom workflows."""

    workspace_id: str | None = None
    type: WorkflowType
    title: str = Field(min_length=1, max_length=200)
    practice_area: str | None = None
    prompt_md: str | None = None
    columns_config: list[dict[str, Any]] | None = None
    flow_json: FlowJson
    input_schema: dict[str, Any] | None = None
    evidence_profile: EvidenceProfile
    profile: WorkflowProfile = "any"
    requires_approval: bool = False


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"] = "error"
    code: str
    message: str
    step: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

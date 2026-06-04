from __future__ import annotations

import json
from typing import Any

from app.workflows.roles import PICARD_AGENT_ROLES, QUERY_INTENTS, ROLE_PHASE_HINTS
from app.workflows.schema import EvidenceProfile, FlowJson, ValidationIssue, ValidationResult


def _toposort_steps(steps: list[dict[str, Any]]) -> tuple[list[str] | None, str | None]:
    names = [s["name"] for s in steps]
    name_set = set(names)
    if len(names) != len(name_set):
        return None, "duplicate step names"
    indegree = {n: 0 for n in names}
    adj: dict[str, list[str]] = {n: [] for n in names}
    for step in steps:
        for dep in step.get("depends_on") or []:
            if dep not in name_set:
                return None, f"depends_on references unknown step '{dep}'"
            indegree[step["name"]] += 1
            adj[dep].append(step["name"])
    queue = [n for n in names if indegree[n] == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for child in adj[n]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(names):
        return None, "cycle in depends_on graph"
    return order, None


def validate_flow_json(flow: FlowJson | dict[str, Any]) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if isinstance(flow, dict):
        try:
            flow = FlowJson.model_validate(flow)
        except Exception as exc:
            errors.append(ValidationIssue(code="flow_schema", message=str(exc)))
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

    if flow.version != "0.8":
        errors.append(
            ValidationIssue(
                code="flow_version",
                message=f"Unsupported flow_json.version '{flow.version}' (expected 0.8)",
            )
        )

    raw_steps = [s.model_dump(exclude_none=True) for s in flow.steps]
    order, dag_err = _toposort_steps(raw_steps)
    if dag_err:
        errors.append(ValidationIssue(code="dag", message=dag_err))

    step_roles: list[str] = []
    for step in flow.steps:
        if step.role not in PICARD_AGENT_ROLES:
            errors.append(
                ValidationIssue(
                    code="unknown_role",
                    message=f"Unknown role '{step.role}'",
                    step=step.name,
                )
            )
        else:
            step_roles.append(step.role)
            phase = ROLE_PHASE_HINTS.get(step.role)
            if phase:
                warnings.append(
                    ValidationIssue(
                        level="warning",
                        code="future_phase_role",
                        message=f"Role '{step.role}' requires {phase} to execute",
                        step=step.name,
                    )
                )

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def validate_evidence_profile(
    profile: EvidenceProfile | dict[str, Any],
    *,
    step_roles: list[str],
) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if isinstance(profile, dict):
        try:
            profile = EvidenceProfile.model_validate(profile)
        except Exception as exc:
            errors.append(ValidationIssue(code="evidence_schema", message=str(exc)))
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

    if profile.allowed_intents:
        bad = [i for i in profile.allowed_intents if i not in QUERY_INTENTS]
        if bad:
            errors.append(
                ValidationIssue(
                    code="invalid_intent",
                    message=f"Unknown allowed_intents: {bad}",
                )
            )

    denied = set(profile.denied_roles or [])
    for role in step_roles:
        if role in denied:
            errors.append(
                ValidationIssue(
                    code="denied_role",
                    message=f"Step uses role '{role}' which is in evidence_profile.denied_roles",
                )
            )

    if not profile.allows_web and "web" in step_roles:
        errors.append(
            ValidationIssue(
                code="web_not_allowed",
                message="flow has web step but evidence_profile.allows_web is false",
            )
        )

    if "writer" in step_roles:
        warnings.append(
            ValidationIssue(
                level="warning",
                code="writer_phase8",
                message="Writer steps need Phase 8 execution",
            )
        )

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def validate_workflow_record(
    *,
    flow_json: str | dict[str, Any],
    evidence_profile_json: str | dict[str, Any],
) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    try:
        flow_data = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
    except json.JSONDecodeError as exc:
        return ValidationResult(
            valid=False,
            errors=[ValidationIssue(code="flow_json", message=f"Invalid JSON: {exc}")],
        )

    try:
        profile_data = (
            json.loads(evidence_profile_json)
            if isinstance(evidence_profile_json, str)
            else evidence_profile_json
        )
    except json.JSONDecodeError as exc:
        return ValidationResult(
            valid=False,
            errors=[ValidationIssue(code="evidence_profile", message=f"Invalid JSON: {exc}")],
        )

    flow_result = validate_flow_json(flow_data)
    errors.extend(flow_result.errors)
    warnings.extend(flow_result.warnings)

    step_roles = [s.role for s in FlowJson.model_validate(flow_data).steps]
    ep_result = validate_evidence_profile(profile_data, step_roles=step_roles)
    errors.extend(ep_result.errors)
    warnings.extend(ep_result.warnings)

    valid = not errors
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)

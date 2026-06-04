"""Built-in workflow playbooks seeded on first DB init."""

from __future__ import annotations

from typing import Any

# Tabular column presets (mirrors frontend/lib/tabular/columnPresets.ts)
_COL_PARTIES = {
    "key": "parties",
    "label": "Parties",
    "format": "bulleted_list",
    "prompt": (
        "List every party: applicants, respondents, informants, opposite parties, and entities "
        "in the caption or first pages. Full name and role per bullet."
    ),
}
_COL_GOV = {
    "key": "governing_law",
    "label": "Governing Law",
    "format": "text",
    "prompt": 'State only the governing law. If not specified, write "Not specified".',
}
_COL_DATE = {
    "key": "effective_date",
    "label": "Effective Date",
    "format": "date",
    "prompt": 'State the effective date in DD Mon YYYY format, or "Not specified".',
}
_COL_TERM = {
    "key": "termination",
    "label": "Termination",
    "format": "text",
    "prompt": "Summarize termination triggers, notice, cure period, and consequences (max 2 sentences).",
}
_COL_CONF = {
    "key": "confidentiality",
    "label": "Confidentiality",
    "format": "text",
    "prompt": "Summarize confidentiality scope, exceptions, and duration (max 2 sentences).",
}

CONTRACT_COLUMNS = [_COL_PARTIES, _COL_GOV, _COL_DATE, _COL_TERM, _COL_CONF]

NDA_COLUMNS = [_COL_PARTIES, _COL_DATE, _COL_CONF, _COL_GOV]

REGULATORY_COLUMNS = [
    _COL_PARTIES,
    {
        "key": "governing_law",
        "label": "Statute / Jurisdiction",
        "format": "text",
        "prompt": 'State applicable statute and jurisdiction. If absent, write "Not specified".',
    },
    {
        "key": "effective_date",
        "label": "Order Date",
        "format": "date",
        "prompt": 'State order date from caption in DD Mon YYYY format, or "Not specified".',
    },
    _COL_CONF,
    _COL_TERM,
]

LITIGATION_COLUMNS = [
    _COL_PARTIES,
    {
        "key": "governing_law",
        "label": "Court / Jurisdiction",
        "format": "text",
        "prompt": "State court and jurisdiction from caption or first pages.",
    },
    {
        "key": "effective_date",
        "label": "Filing Date",
        "format": "date",
        "prompt": 'State filing or order date in DD Mon YYYY format, or "Not specified".',
    },
    {
        "key": "case_posture",
        "label": "Case Posture",
        "format": "text",
        "prompt": "Summarize claims, relief sought, and procedural posture in 1-2 sentences.",
    },
]

MINIMAL_COLUMNS = [
    _COL_PARTIES,
    {
        "key": "document_summary",
        "label": "Document Summary",
        "format": "text",
        "prompt": "Provide a 1-2 sentence summary of what this document is and its key subject matter.",
    },
]


def _research_flow(*, query_template: str = "{{input.question}}") -> dict[str, Any]:
    return {
        "version": "0.8",
        "steps": [
            {
                "name": "research",
                "role": "research",
                "refuse_on_empty": True,
                "query": {"template": query_template},
            }
        ],
    }


def _corpus_profile(*, intents: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
    base = {
        "requires_corpus": True,
        "allowed_intents": intents,
        "allows_tabular": False,
        "allows_csv": False,
        "allows_web": False,
        "denied_roles": None,
    }
    base.update(kwargs)
    return base


def builtin_workflow_defs() -> list[dict[str, Any]]:
    """Return row dicts ready for Workflow ORM insert."""
    defs: list[dict[str, Any]] = []

    def add(
        wid: str,
        *,
        type_: str,
        title: str,
        practice_area: str,
        flow_json: dict[str, Any],
        evidence_profile: dict[str, Any],
        profile: str = "any",
        prompt_md: str | None = None,
        columns_config: list[dict[str, Any]] | None = None,
        input_schema: dict[str, Any] | None = None,
        requires_approval: bool = False,
    ) -> None:
        defs.append(
            {
                "id": wid,
                "workspace_id": None,
                "type": type_,
                "title": title,
                "practice_area": practice_area,
                "prompt_md": prompt_md,
                "columns_config_json": columns_config,
                "flow_json": flow_json,
                "flow_version": "lightflow-0.8",
                "input_schema_json": input_schema,
                "evidence_profile_json": evidence_profile,
                "profile": profile,
                "source": "builtin",
                "requires_approval": requires_approval,
                "is_builtin": 1,
            }
        )

    # --- Assistant playbooks (8) ---
    add(
        "builtin:matter-overview",
        type_="assistant",
        title="Matter overview",
        practice_area="litigation",
        prompt_md=(
            "Provide a structured overview of this matter: parties, forum, key claims, "
            "procedural posture, and recent filings. Cite every factual claim."
        ),
        flow_json=_research_flow(),
        evidence_profile=_corpus_profile(intents=["case_overview"]),
    )
    add(
        "builtin:party-listing",
        type_="assistant",
        title="Party matter listing",
        practice_area="litigation",
        prompt_md=(
            "List all cases or matters involving the named party across the workspace. "
            "Use per-document sections with citations."
        ),
        flow_json=_research_flow(),
        evidence_profile=_corpus_profile(intents=["entity_matter_listing"]),
    )
    add(
        "builtin:obligations",
        type_="assistant",
        title="Obligations extract",
        practice_area="contracts",
        prompt_md="Identify and summarize contractual obligations with section citations.",
        flow_json=_research_flow(),
        evidence_profile=_corpus_profile(intents=["obligations"]),
    )
    add(
        "builtin:timeline",
        type_="assistant",
        title="Chronology / timeline",
        practice_area="litigation",
        prompt_md="Build a dated chronology of key events with citations.",
        flow_json=_research_flow(),
        evidence_profile=_corpus_profile(intents=["timeline"]),
    )
    add(
        "builtin:factual-lookup",
        type_="assistant",
        title="Factual lookup",
        practice_area="general",
        prompt_md="Answer the question using only cited passages from the scoped documents.",
        flow_json=_research_flow(),
        evidence_profile=_corpus_profile(intents=["factual_lookup", "general"]),
    )
    add(
        "builtin:case-context",
        type_="assistant",
        title="Multi-constraint case context",
        practice_area="litigation",
        prompt_md=(
            "Answer using CARP-style multi-constraint retrieval when the question spans "
            "several dimensions (party, statute, outcome)."
        ),
        flow_json=_research_flow(),
        evidence_profile=_corpus_profile(intents=["case_context"]),
    )
    add(
        "builtin:dd-memo",
        type_="assistant",
        title="Due diligence memo",
        practice_area="transactions",
        profile="firm",
        prompt_md=(
            "Draft a concise due diligence memo covering material terms, risks, and open items. "
            "Every legal fact must be cited."
        ),
        flow_json=_research_flow(query_template="{{input.question}}"),
        evidence_profile=_corpus_profile(intents=["case_overview", "obligations", "factual_lookup"]),
    )
    add(
        "builtin:compliance-checklist",
        type_="assistant",
        title="Compliance checklist",
        practice_area="compliance",
        profile="court",
        requires_approval=True,
        prompt_md="Run a filing/compliance checklist against scoped admin documents.",
        flow_json={
            "version": "0.8",
            "steps": [
                {"name": "checklist", "role": "compliance", "refuse_on_empty": True},
                {"name": "cite_verify", "role": "research", "depends_on": ["checklist"]},
            ],
        },
        evidence_profile=_corpus_profile(
            intents=["factual_lookup"],
            denied_roles=["web"],
        ),
    )

    # --- Tabular playbooks (6) ---
    tabular_specs = [
        ("builtin:tabular-contract", "Contract due diligence", "transactions", CONTRACT_COLUMNS, "Contract review"),
        ("builtin:tabular-nda", "NDA review", "transactions", NDA_COLUMNS, "NDA review"),
        ("builtin:tabular-regulatory", "Regulatory / CCI", "regulatory", REGULATORY_COLUMNS, "Regulatory review"),
        ("builtin:tabular-litigation", "Litigation summary", "litigation", LITIGATION_COLUMNS, "Litigation summary"),
        ("builtin:tabular-minimal", "Quick scan", "general", MINIMAL_COLUMNS, "Quick scan"),
        (
            "builtin:tabular-msa",
            "MSA review",
            "transactions",
            CONTRACT_COLUMNS,
            "MSA review",
        ),
    ]
    for wid, title, area, cols, default_title in tabular_specs:
        add(
            wid,
            type_="tabular",
            title=title,
            practice_area=area,
            prompt_md=f"Start a tabular review: {default_title}",
            columns_config=cols,
            flow_json={
                "version": "0.8",
                "input_hint": "Select documents then run column extraction (Phase 7b).",
                "steps": [{"name": "extract", "role": "tabular", "refuse_on_empty": False}],
            },
            evidence_profile={
                "requires_corpus": True,
                "allowed_intents": None,
                "allows_tabular": True,
                "allows_csv": False,
                "allows_web": False,
            },
        )

    # --- Composite lightflow stubs (4) ---
    add(
        "builtin:contracts-agent-qa",
        type_="lightflow",
        title="Contracts agent Q&A",
        practice_area="transactions",
        prompt_md="Upload contracts, wait for parse, then ask cited questions (UC-2).",
        flow_json={
            "version": "0.8",
            "steps": [
                {
                    "name": "answer",
                    "role": "research",
                    "refuse_on_empty": True,
                    "query": {"template": "{{input.question}}"},
                }
            ],
        },
        evidence_profile=_corpus_profile(intents=["factual_lookup", "general"]),
        input_schema={"required": ["document_ids"], "optional": ["question"]},
    )
    add(
        "builtin:web-to-corpus-qa",
        type_="lightflow",
        title="Web → corpus Q&A",
        practice_area="research",
        profile="firm",
        prompt_md="Fetch approved URLs, ingest into vault, then answer from corpus only (UC-1).",
        flow_json={
            "version": "0.8",
            "steps": [
                {"name": "fetch", "role": "web", "config": {"urls_from_input": True}},
                {
                    "name": "ingest",
                    "role": "research",
                    "depends_on": ["fetch"],
                    "config": {"action": "ingest_web_snapshot"},
                },
                {
                    "name": "wait",
                    "role": "research",
                    "depends_on": ["ingest"],
                    "config": {"action": "wait_parse"},
                },
                {
                    "name": "answer",
                    "role": "research",
                    "depends_on": ["wait"],
                    "refuse_on_empty": True,
                    "query": {"template": "{{input.question}}"},
                },
            ],
        },
        evidence_profile=_corpus_profile(intents=["factual_lookup"], allows_web=True),
        input_schema={"required": ["urls"], "optional": ["question"]},
    )
    add(
        "builtin:guideline-csv-draft",
        type_="lightflow",
        title="Guideline + CSV draft",
        practice_area="transactions",
        profile="firm",
        prompt_md="Bind CSV parties, research guidelines, draft template sections (UC-3).",
        flow_json={
            "version": "0.8",
            "steps": [
                {"name": "bind_csv", "role": "tabular", "config": {"csv_file_id_from_input": True}},
                {
                    "name": "guidelines",
                    "role": "research",
                    "depends_on": ["bind_csv"],
                    "refuse_on_empty": True,
                },
                {
                    "name": "draft",
                    "role": "writer",
                    "depends_on": ["guidelines", "bind_csv"],
                    "cite_from_steps": ["guidelines"],
                },
                {"name": "review", "role": "compliance", "depends_on": ["draft"]},
            ],
        },
        evidence_profile=_corpus_profile(
            intents=["obligations", "factual_lookup"],
            allows_csv=True,
            allows_tabular=True,
        ),
        input_schema={"required": ["csv_file_id", "guideline_doc_ids", "template_id"]},
    )
    add(
        "builtin:court-filing-defect",
        type_="lightflow",
        title="Court filing defect scan",
        practice_area="litigation",
        profile="court",
        requires_approval=True,
        prompt_md="Scan filings for defects against court checklist; admin scope only.",
        flow_json={
            "version": "0.8",
            "steps": [
                {"name": "scan", "role": "compliance", "refuse_on_empty": True},
                {"name": "context", "role": "research", "depends_on": ["scan"]},
            ],
        },
        evidence_profile=_corpus_profile(
            intents=["factual_lookup"],
            denied_roles=["web"],
        ),
    )

    return defs

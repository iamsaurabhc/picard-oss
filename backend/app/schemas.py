from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    matter_ref: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    matter_ref: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    matter_ref: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class WorkspaceDocumentCountsOut(BaseModel):
    total: int = 0
    done: int = 0
    pending: int = 0
    parsing: int = 0
    error: int = 0


class PartyHighlightOut(BaseModel):
    display_value: str
    document_count: int


class DocTypeCountOut(BaseModel):
    doc_type: str
    count: int


class WorkspaceOverviewOut(BaseModel):
    workspace: WorkspaceOut
    documents: WorkspaceDocumentCountsOut
    tabular_reviews: int
    parties: list[PartyHighlightOut] = Field(default_factory=list)
    doc_types: list[DocTypeCountOut] = Field(default_factory=list)
    recent_documents: list["DocumentOut"] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: str
    workspace_id: str
    file_name: str
    content_hash: str | None
    page_count: int | None
    parse_status: str
    parse_error: str | None
    text_source: str | None = None
    ocr_engine: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class OcrHealthOut(BaseModel):
    configured: bool
    server_url: str | None
    reachable: bool
    engine: str
    tesseract_ready: bool = False


class DocumentRetryAllOut(BaseModel):
    retried_count: int
    document_ids: list[str]


class ChunkOut(BaseModel):
    id: str
    document_id: str
    page_number: int
    chunk_type: Literal["heading", "paragraph", "table", "list"]
    bbox: dict
    text_content: str
    heading_path: str | None
    section_key: str | None
    token_count: int | None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    workspace_id: str
    top_k: int = 12
    document_ids: list[str] | None = None
    metadata_filters: dict[str, str] | None = None
    retrieval_mode: Literal["auto", "simple", "multi_constraint"] = "auto"
    proximity_max_tier: str = "SAME_SECTION"
    allow_partial_disclosure: bool = False
    min_score: float | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int
    text_content: str
    heading_path: str | None
    section_key: str | None = None
    bbox: dict | None = None
    score: float


class ContextBundleOut(BaseModel):
    bundle_id: str
    document_id: str
    page_start: int
    page_end: int
    section_key: str | None
    heading_path: str | None
    chunk_ids: list[str]
    constraints_matched: list[str]
    constraints_missing: list[str]
    proximity_tier: str
    bm25_score: float
    coherence_score: float
    score: float


class SearchResponse(BaseModel):
    mode: Literal["SIMPLE", "MULTI_CONSTRAINT"]
    hits: list[SearchHit]
    bundles: list[ContextBundleOut] | None = None
    retrieval_diagnostics: dict | None = None
    proximity_tier_used: str | None = None
    refused: bool = False
    expanded_query: str | None = None
    suggestions: list[str] = Field(default_factory=list)


class ChatSessionCreate(BaseModel):
    workspace_id: str
    title: str | None = None
    reuse_draft: bool = True


class ChatSessionSummary(BaseModel):
    id: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int
    has_user_message: bool = False
    preview: str | None = None


class ChatSessionOut(BaseModel):
    id: str
    workspace_id: str | None
    title: str | None
    created_at: str
    updated_at: str
    document_ids: list[str] = Field(default_factory=list)


class ChatSessionUpdate(BaseModel):
    title: str | None = None
    document_ids: list[str] | None = None


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    references: list[dict] | None = None
    refused: bool = False
    created_at: str


class ChatStreamRequest(BaseModel):
    session_id: str
    workspace_id: str
    message: str = Field(min_length=1)
    mode: Literal["rag", "agent"] = "rag"
    document_ids: list[str] | None = None
    retrieval_mode: Literal["auto", "simple", "multi_constraint"] = "auto"
    allow_partial_disclosure: bool = False
    top_k: int = 12
    tabular_review_id: str | None = None
    workflow_id: str | None = None
    agent_run_id: str | None = None
    approval_token: str | None = None


class AgentRunOut(BaseModel):
    id: str
    session_id: str | None
    workspace_id: str
    profile: str
    mode: str
    plan_json: dict | None = None
    events: list[dict] = Field(default_factory=list)
    status: str
    created_at: str
    updated_at: str


ColumnFormat = Literal[
    "text",
    "bulleted_list",
    "number",
    "currency",
    "yes_no",
    "date",
    "tag",
    "percentage",
    "monetary_amount",
]

CellFlag = Literal["green", "grey", "yellow", "red"]
CellStatus = Literal["pending", "generating", "done", "error"]


class TabularColumn(BaseModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    format: ColumnFormat = "text"
    prompt: str = Field(min_length=1)
    tag_options: list[str] | None = None


class TabularReviewCreate(BaseModel):
    workspace_id: str
    title: str = Field(min_length=1, max_length=200)
    columns: list[TabularColumn] = Field(min_length=1)
    document_ids: list[str] = Field(min_length=1)


class TabularReviewUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    columns: list[TabularColumn] | None = None
    document_ids: list[str] | None = None


class TabularCellOut(BaseModel):
    id: str
    review_id: str
    document_id: str
    column_key: str
    summary: str | None = None
    reasoning: str | None = None
    flag: CellFlag | None = None
    status: CellStatus
    source_chunk_ids: list[str] = Field(default_factory=list)


class TabularReviewSummary(BaseModel):
    id: str
    workspace_id: str
    title: str
    column_count: int
    document_count: int
    created_at: str


class TabularReviewOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    columns: list[TabularColumn]
    document_ids: list[str]
    documents: list[DocumentOut]
    cells: list[TabularCellOut]
    created_at: str


class GenerateColumnPromptRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    format: ColumnFormat | None = None
    idea: str | None = Field(default=None, max_length=2000)


class GenerateColumnPromptResponse(BaseModel):
    prompt: str
    from_preset: bool = False
    suggested_format: ColumnFormat = "text"


class TabularBatchGenerateRequest(BaseModel):
    document_ids: list[str] | None = None
    column_keys: list[str] | None = None
    only_pending: bool = True


WorkflowType = Literal["assistant", "tabular", "lightflow"]
WorkflowProfile = Literal["firm", "court", "any"]


class WorkflowValidationIssueOut(BaseModel):
    level: Literal["error", "warning"] = "error"
    code: str
    message: str
    step: str | None = None


class WorkflowValidationOut(BaseModel):
    valid: bool
    errors: list[WorkflowValidationIssueOut] = Field(default_factory=list)
    warnings: list[WorkflowValidationIssueOut] = Field(default_factory=list)


class WorkflowOut(BaseModel):
    id: str
    workspace_id: str | None = None
    type: WorkflowType
    title: str
    practice_area: str | None = None
    prompt_md: str | None = None
    columns_config: list[dict] | None = None
    flow_json: dict
    flow_version: str
    input_schema: dict | None = None
    evidence_profile: dict
    profile: WorkflowProfile
    source: str
    requires_approval: bool
    is_builtin: bool
    created_at: str
    updated_at: str


class WorkflowCreate(BaseModel):
    workspace_id: str | None = None
    type: WorkflowType
    title: str = Field(min_length=1, max_length=200)
    practice_area: str | None = None
    prompt_md: str | None = None
    columns_config: list[TabularColumn] | None = None
    flow_json: dict
    input_schema: dict | None = None
    evidence_profile: dict
    profile: WorkflowProfile = "any"
    requires_approval: bool = False

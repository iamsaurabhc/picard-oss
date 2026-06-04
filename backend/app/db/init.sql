-- Picard-OSS SQLite schema (Phase 1)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  matter_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  file_name TEXT NOT NULL,
  local_path TEXT NOT NULL,
  content_hash TEXT,
  page_count INTEGER,
  parse_status TEXT DEFAULT 'pending',
  parse_error TEXT,
  text_source TEXT,
  ocr_engine TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_number INTEGER NOT NULL,
  chunk_type TEXT NOT NULL,
  bbox_json TEXT NOT NULL,
  text_content TEXT NOT NULL,
  heading_path TEXT,
  section_key TEXT,
  token_count INTEGER,
  FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text_content,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS metadata_tags (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  tag_key TEXT NOT NULL,
  tag_value TEXT NOT NULL,
  source_chunk_id TEXT,
  FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  canonical_value TEXT NOT NULL,
  display_value TEXT NOT NULL,
  UNIQUE(workspace_id, entity_type, canonical_value)
);

CREATE TABLE IF NOT EXISTS entity_mentions (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  page_number INTEGER NOT NULL,
  char_start INTEGER,
  char_end INTEGER,
  surface_text TEXT NOT NULL,
  confidence REAL DEFAULT 1.0,
  source TEXT DEFAULT 'rule',
  FOREIGN KEY (entity_id) REFERENCES entities(id),
  FOREIGN KEY (document_id) REFERENCES documents(id),
  FOREIGN KEY (chunk_id) REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS page_entities (
  document_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  mention_count INTEGER DEFAULT 1,
  PRIMARY KEY (document_id, page_number, entity_id),
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES entities(id)
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  embedding_blob BLOB NOT NULL,
  model_id TEXT NOT NULL,
  dims INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_document
  ON chunk_embeddings(document_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  workspace_id TEXT,
  title TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  document_ids_json TEXT,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  references_json TEXT,
  refused INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tabular_reviews (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  columns_config_json TEXT NOT NULL,
  document_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS tabular_cells (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES tabular_reviews(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  column_key TEXT NOT NULL,
  summary TEXT,
  reasoning TEXT,
  flag TEXT,
  status TEXT DEFAULT 'pending',
  source_chunk_ids_json TEXT,
  UNIQUE(review_id, document_id, column_key),
  FOREIGN KEY (review_id) REFERENCES tabular_reviews(id),
  FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  progress REAL DEFAULT 0,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Phase 6: workflow library
CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  workspace_id TEXT,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  practice_area TEXT,
  prompt_md TEXT,
  columns_config_json TEXT,
  flow_json TEXT NOT NULL,
  flow_version TEXT DEFAULT 'lightflow-0.8',
  input_schema_json TEXT,
  evidence_profile_json TEXT NOT NULL,
  profile TEXT DEFAULT 'any',
  source TEXT DEFAULT 'builtin',
  requires_approval INTEGER DEFAULT 0,
  is_builtin INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hidden_workflows (
  workflow_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_workflows_workspace ON workflows(workspace_id);
CREATE INDEX IF NOT EXISTS idx_workflows_type ON workflows(type);
CREATE INDEX IF NOT EXISTS idx_workflows_profile ON workflows(profile);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_document_page ON chunks(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_chunks_document_section ON chunks(document_id, section_key);
CREATE INDEX IF NOT EXISTS idx_metadata_tags_doc_key ON metadata_tags(document_id, tag_key);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(entity_id, document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_page ON entity_mentions(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_page_entities_entity ON page_entities(entity_id, document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_entities_workspace ON entities(workspace_id, entity_type, canonical_value);

-- FTS5 sync triggers
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text_content) VALUES (new.rowid, new.text_content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text_content) VALUES('delete', old.rowid, old.text_content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text_content) VALUES('delete', old.rowid, old.text_content);
  INSERT INTO chunks_fts(rowid, text_content) VALUES (new.rowid, new.text_content);
END;

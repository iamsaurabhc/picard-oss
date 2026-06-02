import type { ColumnFormat, TabularColumn } from "@/lib/picardApi";

export type TabularTemplateId =
  | "contract"
  | "contract_full"
  | "regulatory"
  | "nda"
  | "msa"
  | "litigation"
  | "minimal";

export type TabularTemplate = {
  id: TabularTemplateId;
  name: string;
  description: string;
  defaultTitle: string;
  columns: TabularColumn[];
};

export const DEFAULT_PRESET_COLUMNS: TabularColumn[] = [
  {
    key: "parties",
    label: "Parties",
    format: "bulleted_list",
    prompt:
      "List every party: applicants, respondents, informants, opposite parties, and entities in the caption or first pages. Full name and role per bullet. Do not say Not specified if names appear in chunks or the indexed party list.",
  },
  {
    key: "governing_law",
    label: "Governing Law",
    format: "text",
    prompt: 'State only the governing law, e.g. "New York Law". If not specified, write "Not specified".',
  },
  {
    key: "effective_date",
    label: "Effective Date",
    format: "date",
    prompt: 'State the effective date in DD Mon YYYY format, or "Not specified".',
  },
  {
    key: "termination",
    label: "Termination",
    format: "text",
    prompt: "Summarize termination triggers, notice, cure period, and consequences (max 2 sentences).",
  },
  {
    key: "confidentiality",
    label: "Confidentiality",
    format: "text",
    prompt: "Summarize confidentiality scope, exceptions, and duration (max 2 sentences).",
  },
];

const CONTRACT_FULL_COLUMNS: TabularColumn[] = [
  ...DEFAULT_PRESET_COLUMNS.slice(0, 3),
  {
    key: "term",
    label: "Term",
    format: "text",
    prompt:
      'State only the duration or term in concise form, e.g. "3 years", "24 months", "perpetual".',
  },
  DEFAULT_PRESET_COLUMNS[3],
  {
    key: "change_of_control",
    label: "Change of Control",
    format: "text",
    prompt:
      "Identify change of control provisions: triggers, consequences, consent requirements (max 2 sentences).",
  },
  DEFAULT_PRESET_COLUMNS[4],
  {
    key: "assignment",
    label: "Assignment",
    format: "yes_no",
    prompt: "Is assignment of this agreement permitted without the other party's consent?",
  },
];

export const REGULATORY_PRESET_COLUMNS: TabularColumn[] = [
  {
    key: "parties",
    label: "Parties",
    format: "bulleted_list",
    prompt:
      "List every party to this matter: informants, opposite parties, DG, Commission, and companies in the caption. One party per bullet with role.",
  },
  {
    key: "governing_law",
    label: "Statute / Jurisdiction",
    format: "text",
    prompt:
      'State applicable statute and jurisdiction (e.g. "Competition Act 2002, India"). If absent, write "Not specified".',
  },
  {
    key: "effective_date",
    label: "Order Date",
    format: "date",
    prompt: 'State order date from caption in DD Mon YYYY format, or "Not specified".',
  },
  {
    key: "confidentiality",
    label: "Confidentiality of Filing",
    format: "text",
    prompt: "Summarize confidentiality of investigation filings in 1-2 sentences.",
  },
  {
    key: "termination",
    label: "Suspension / Closure",
    format: "text",
    prompt: "Summarize order provisions on suspension, closure, or investigation termination (1-2 sentences).",
  },
];

const NDA_COLUMNS: TabularColumn[] = [
  DEFAULT_PRESET_COLUMNS[0],
  DEFAULT_PRESET_COLUMNS[2],
  {
    key: "term",
    label: "Term",
    format: "text",
    prompt:
      'State confidentiality/survival term in concise form, e.g. "3 years", "perpetual". If not specified, write "Not specified".',
  },
  DEFAULT_PRESET_COLUMNS[4],
  DEFAULT_PRESET_COLUMNS[1],
];

const MSA_COLUMNS: TabularColumn[] = [
  DEFAULT_PRESET_COLUMNS[0],
  {
    key: "term",
    label: "Term",
    format: "text",
    prompt:
      'State service term or renewal period concisely, e.g. "1 year with auto-renewal".',
  },
  DEFAULT_PRESET_COLUMNS[3],
  {
    key: "assignment",
    label: "Assignment",
    format: "yes_no",
    prompt: "Is assignment permitted without consent?",
  },
  DEFAULT_PRESET_COLUMNS[1],
  DEFAULT_PRESET_COLUMNS[4],
];

const LITIGATION_COLUMNS: TabularColumn[] = [
  {
    key: "parties",
    label: "Parties",
    format: "bulleted_list",
    prompt:
      "List plaintiff, defendant, and other parties from the caption or first pages. One party per bullet with role.",
  },
  {
    key: "governing_law",
    label: "Court / Jurisdiction",
    format: "text",
    prompt:
      "State court and jurisdiction from caption or first pages. If absent, write Not specified.",
  },
  {
    key: "effective_date",
    label: "Filing Date",
    format: "date",
    prompt: 'State filing or order date in DD Mon YYYY format, or "Not specified".',
  },
  {
    key: "case_posture",
    label: "Case Posture",
    format: "text",
    prompt:
      "Summarize claims, relief sought, and procedural posture in 1-2 sentences.",
  },
];

const MINIMAL_COLUMNS: TabularColumn[] = [
  DEFAULT_PRESET_COLUMNS[0],
  {
    key: "document_summary",
    label: "Document Summary",
    format: "text",
    prompt: "Provide a 1-2 sentence summary of what this document is and its key subject matter.",
  },
];

export const TABULAR_TEMPLATES: TabularTemplate[] = [
  {
    id: "contract",
    name: "Contract due diligence",
    description: "Core commercial terms for agreement reviews.",
    defaultTitle: "Contract review",
    columns: DEFAULT_PRESET_COLUMNS,
  },
  {
    id: "contract_full",
    name: "Contract DD (full)",
    description: "Eight columns including term, change of control, and assignment.",
    defaultTitle: "Contract DD (full)",
    columns: CONTRACT_FULL_COLUMNS,
  },
  {
    id: "regulatory",
    name: "Regulatory / CCI",
    description: "Investigation orders, statutes, and filing confidentiality.",
    defaultTitle: "Regulatory review",
    columns: REGULATORY_PRESET_COLUMNS,
  },
  {
    id: "nda",
    name: "NDA review",
    description: "Parties, term, confidentiality, and governing law.",
    defaultTitle: "NDA review",
    columns: NDA_COLUMNS,
  },
  {
    id: "msa",
    name: "MSA review",
    description: "Master service agreement key commercial clauses.",
    defaultTitle: "MSA review",
    columns: MSA_COLUMNS,
  },
  {
    id: "litigation",
    name: "Litigation summary",
    description: "Parties, court, filing date, and case posture.",
    defaultTitle: "Litigation summary",
    columns: LITIGATION_COLUMNS,
  },
  {
    id: "minimal",
    name: "Quick scan",
    description: "Parties plus a short document summary.",
    defaultTitle: "Quick scan",
    columns: MINIMAL_COLUMNS,
  },
];

export const COLUMN_FORMATS: { value: ColumnFormat; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "bulleted_list", label: "Bulleted list" },
  { value: "yes_no", label: "Yes / No" },
  { value: "date", label: "Date" },
  { value: "number", label: "Number" },
  { value: "currency", label: "Currency" },
];

export function columnKeyFromLabel(label: string): string {
  const key = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return key || "column";
}

export function ensureUniqueColumnKey(baseKey: string, existingKeys: string[]): string {
  let key = baseKey;
  let n = 2;
  while (existingKeys.includes(key)) {
    key = `${baseKey}_${n}`;
    n += 1;
  }
  return key;
}

/** Mirrors backend filename doc_type heuristics for mixed-corpus warnings. */
export function inferDocTypeFromFileName(fileName: string): string | null {
  const n = fileName.toLowerCase();
  if (n.includes("nda")) return "nda";
  if (n.includes("msa") || n.includes("master_service")) return "msa";
  if (n.includes("lease")) return "lease";
  if (["complaint", "petition", "judgment", "appeal"].some((k) => n.includes(k))) return "litigation";
  if (["regulation", "cci", "commission", "informant"].some((k) => n.includes(k))) return "regulatory";
  if (n.includes("agreement") || n.includes("contract")) return "contract";
  return null;
}

export function mixedDocTypeWarning(fileNames: string[]): string | null {
  const types = new Set(
    fileNames.map(inferDocTypeFromFileName).filter((t): t is string => Boolean(t))
  );
  if (types.size < 2) return null;
  const labels = Array.from(types).sort().join(", ");
  return `Selected documents span multiple types (${labels}). Contract columns may show N/A or weak results on litigation or regulatory files — consider separate reviews or the regulatory preset.`;
}

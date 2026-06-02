"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { TabularColumn } from "@/lib/picardApi";
import { picardApi } from "@/lib/picardApi";
import {
  mixedDocTypeWarning,
  TABULAR_TEMPLATES,
  type TabularTemplateId,
} from "@/lib/tabular/columnPresets";
import { Button } from "@/components/ui/button";

type Props = {
  open: boolean;
  workspaceId: string;
  onClose: () => void;
  onCreated: (reviewId: string) => void;
};

export function AddNewTRModal({ open, workspaceId, onClose, onCreated }: Props) {
  const [title, setTitle] = useState("Contract review");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [templateId, setTemplateId] = useState<TabularTemplateId>("contract");
  const [saving, setSaving] = useState(false);

  const template = TABULAR_TEMPLATES.find((t) => t.id === templateId) ?? TABULAR_TEMPLATES[0];

  const { data: documents = [] } = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => picardApi.listDocuments(workspaceId),
    enabled: open,
  });

  const parsed = documents.filter((d) => d.parse_status === "done");

  const mixedWarning = useMemo(() => {
    const names = parsed.filter((d) => selected.has(d.id)).map((d) => d.file_name);
    return mixedDocTypeWarning(names);
  }, [parsed, selected]);

  useEffect(() => {
    if (open) {
      setTemplateId("contract");
      setTitle(TABULAR_TEMPLATES[0].defaultTitle);
    }
  }, [open]);

  if (!open) return null;

  function selectTemplate(id: TabularTemplateId) {
    const t = TABULAR_TEMPLATES.find((x) => x.id === id);
    if (!t) return;
    setTemplateId(id);
    setTitle(t.defaultTitle);
  }

  async function handleCreate() {
    const docIds = Array.from(selected);
    if (!docIds.length) return;
    setSaving(true);
    try {
      const columns: TabularColumn[] = template.columns;
      const review = await picardApi.createTabularReview({
        workspace_id: workspaceId,
        title: title.trim() || template.defaultTitle,
        columns,
        document_ids: docIds,
      });
      onCreated(review.id);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-lg">
        <h2 className="mb-4 font-serif text-lg">New tabular review</h2>
        <label className="mb-1 block text-xs font-medium text-neutral-600">Title</label>
        <input
          className="mb-4 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <p className="mb-2 text-xs font-medium text-neutral-600">Template</p>
        <div className="mb-4 max-h-56 space-y-2 overflow-y-auto">
          {TABULAR_TEMPLATES.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => selectTemplate(t.id)}
              className={`w-full rounded border px-3 py-2 text-left text-sm transition-colors ${
                templateId === t.id
                  ? "border-neutral-900 bg-neutral-50"
                  : "border-neutral-200 hover:border-neutral-400"
              }`}
            >
              <span className="font-medium text-neutral-900">{t.name}</span>
              <span className="mt-0.5 block text-xs text-neutral-500">
                {t.description} · {t.columns.length} columns
              </span>
            </button>
          ))}
        </div>
        <p className="mb-2 text-xs text-neutral-500">
          Columns: {template.columns.map((c) => c.label).join(", ")}
        </p>
        <p className="mb-2 text-xs font-medium text-neutral-600">Documents (parsed PDFs only)</p>
        <div className="mb-4 max-h-48 overflow-y-auto rounded border border-neutral-200">
          {parsed.length === 0 ? (
            <p className="p-4 text-sm text-neutral-500">Upload and parse documents first.</p>
          ) : (
            parsed.map((doc) => (
              <label
                key={doc.id}
                className="flex cursor-pointer items-center gap-2 border-b border-neutral-100 px-3 py-2 text-sm last:border-0 hover:bg-neutral-50"
              >
                <input
                  type="checkbox"
                  checked={selected.has(doc.id)}
                  onChange={() => {
                    const next = new Set(selected);
                    if (next.has(doc.id)) next.delete(doc.id);
                    else next.add(doc.id);
                    setSelected(next);
                  }}
                />
                {doc.file_name}
              </label>
            ))
          )}
        </div>
        {mixedWarning ? (
          <p className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {mixedWarning}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving || selected.size === 0} onClick={handleCreate}>
            {saving ? "Creating…" : "Create review"}
          </Button>
        </div>
      </div>
    </div>
  );
}

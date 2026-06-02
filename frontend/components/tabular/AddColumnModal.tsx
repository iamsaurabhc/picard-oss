"use client";

import { useEffect, useState } from "react";
import type { ColumnFormat, TabularColumn } from "@/lib/picardApi";
import { picardApi } from "@/lib/picardApi";
import { COLUMN_FORMATS, columnKeyFromLabel } from "@/lib/tabular/columnPresets";
import { Button } from "@/components/ui/button";

const IDEA_MIN_LEN = 10;

type Props = {
  open: boolean;
  saving?: boolean;
  onClose: () => void;
  onSave: (column: TabularColumn) => void;
};

export function AddColumnModal({ open, saving, onClose, onSave }: Props) {
  const [label, setLabel] = useState("");
  const [idea, setIdea] = useState("");
  const [format, setFormat] = useState<ColumnFormat>("text");
  const [prompt, setPrompt] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLabel("");
    setIdea("");
    setFormat("text");
    setPrompt("");
    setAdvancedOpen(false);
  }, [open]);

  useEffect(() => {
    if (!open || !label.trim() || idea.trim().length < IDEA_MIN_LEN) return;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await picardApi.generateColumnPrompt({
          label: label.trim(),
          idea: idea.trim(),
          format: advancedOpen ? format : undefined,
        });
        setPrompt(res.prompt);
        if (res.suggested_format) setFormat(res.suggested_format);
      } catch {
        /* keep manual prompt */
      } finally {
        setLoading(false);
      }
    }, 500);
    return () => clearTimeout(t);
  }, [label, idea, format, advancedOpen, open]);

  if (!open) return null;

  const canSubmit = label.trim().length > 0 && idea.trim().length >= IDEA_MIN_LEN && prompt.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h2 className="mb-4 font-serif text-lg">Add column</h2>
        <label className="mb-1 block text-xs font-medium text-neutral-600">Column name</label>
        <input
          className="mb-3 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. Liquidated damages"
        />
        <label className="mb-1 block text-xs font-medium text-neutral-600">What to extract</label>
        <textarea
          className="mb-1 h-20 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          placeholder="Describe what data to pull from each document, e.g. cap amount and triggers for liquidated damages"
        />
        <p className="mb-3 text-xs text-neutral-500">
          {idea.trim().length < IDEA_MIN_LEN
            ? `Add at least ${IDEA_MIN_LEN} characters to generate an extraction prompt.`
            : loading
              ? "Generating extraction prompt…"
              : "Extraction will run across all documents when you confirm."}
        </p>
        <button
          type="button"
          className="mb-2 text-xs text-neutral-600 underline hover:text-neutral-900"
          onClick={() => setAdvancedOpen((o) => !o)}
        >
          {advancedOpen ? "Hide advanced" : "Advanced options"}
        </button>
        {advancedOpen ? (
          <>
            <label className="mb-1 block text-xs font-medium text-neutral-600">Format</label>
            <select
              className="mb-3 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
              value={format}
              onChange={(e) => setFormat(e.target.value as ColumnFormat)}
            >
              {COLUMN_FORMATS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
            <label className="mb-1 block text-xs font-medium text-neutral-600">Extraction prompt</label>
            <textarea
              className="mb-4 h-28 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            disabled={!canSubmit || saving || loading}
            onClick={() => {
              const key = columnKeyFromLabel(label);
              onSave({
                key,
                label: label.trim(),
                format,
                prompt: prompt.trim(),
              });
            }}
          >
            {saving ? "Adding…" : "Add & extract"}
          </Button>
        </div>
      </div>
    </div>
  );
}

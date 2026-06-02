"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { picardApi } from "@/lib/picardApi";
import { Button } from "@/components/ui/button";

type Props = {
  open: boolean;
  workspaceId: string;
  reviewId: string;
  existingDocIds: string[];
  onClose: () => void;
  onUpdated: () => void;
};

export function AddDocumentsModal({
  open,
  workspaceId,
  reviewId,
  existingDocIds,
  onClose,
  onUpdated,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  const { data: documents = [] } = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => picardApi.listDocuments(workspaceId),
    enabled: open,
  });

  const available = documents.filter(
    (d) => d.parse_status === "done" && !existingDocIds.includes(d.id)
  );

  if (!open) return null;

  async function handleAdd() {
    const add = Array.from(selected);
    if (!add.length) return;
    setSaving(true);
    try {
      await picardApi.updateTabularReview(reviewId, {
        document_ids: [...existingDocIds, ...add],
      });
      onUpdated();
      onClose();
      setSelected(new Set());
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="max-h-[80vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-6 shadow-lg">
        <h2 className="mb-4 font-serif text-lg">Add documents</h2>
        {available.length === 0 ? (
          <p className="text-sm text-neutral-500">No additional parsed documents available.</p>
        ) : (
          <div className="mb-4 max-h-48 overflow-y-auto rounded border border-neutral-200">
            {available.map((doc) => (
              <label
                key={doc.id}
                className="flex cursor-pointer items-center gap-2 border-b border-neutral-100 px-3 py-2 text-sm"
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
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving || selected.size === 0} onClick={handleAdd}>
            {saving ? "Adding…" : "Add to review"}
          </Button>
        </div>
      </div>
    </div>
  );
}

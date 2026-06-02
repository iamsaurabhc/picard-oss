"use client";

import { Button } from "@/components/ui/button";

type Props = {
  open: boolean;
  title: string;
  deleting?: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

export function DeleteReviewDialog({ open, title, deleting, onClose, onConfirm }: Props) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-lg">
        <h2 className="mb-2 font-serif text-lg">Delete review?</h2>
        <p className="mb-1 text-sm text-neutral-800">
          <span className="font-medium">{title}</span>
        </p>
        <p className="mb-4 text-sm text-neutral-600">
          All extracted cells for this review will be removed. This cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={deleting}>
            Cancel
          </Button>
          <Button
            className="bg-red-700 text-white hover:bg-red-800"
            onClick={onConfirm}
            disabled={deleting}
          >
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </div>
    </div>
  );
}

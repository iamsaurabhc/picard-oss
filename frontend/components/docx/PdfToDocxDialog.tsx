"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { picardApi } from "@/lib/picardApi";
import type { DocumentRecord } from "@/lib/picardApi";
import { convertPdfToDocx } from "@/lib/pdfToDocx";

type Props = {
  document: DocumentRecord;
  onConverted: (newDocumentId: string) => void;
  onClose: () => void;
};

export function PdfToDocxDialog({ document, onConverted, onClose }: Props) {
  const [progress, setProgress] = useState<string | null>(null);

  const convert = useMutation({
    mutationFn: async () => {
      const isScanned =
        document.text_source === "scanned" || document.text_source === "mixed";

      if (isScanned) {
        setProgress("Building Word document from parsed chunks…");
        const result = await picardApi.convertPdfToDocx(document.id, "chunks");
        return result.document_id;
      }

      setProgress("Loading PDF…");
      const pdfRes = await fetch(picardApi.documentFileUrl(document.id));
      if (!pdfRes.ok) throw new Error("Failed to load PDF");
      const pdfBytes = await pdfRes.arrayBuffer();

      setProgress("Initializing converter…");
      const result = await convertPdfToDocx(pdfBytes, document.file_name, (p) => {
        setProgress(p.message || `Converting… ${p.percent}%`);
      });

      setProgress("Saving to vault…");
      const blob = new Blob([new Uint8Array(result.data)], {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });
      const fileName = document.file_name.replace(/\.pdf$/i, ".docx");
      const file = new File([blob], fileName, {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });
      const saved = await picardApi.uploadDocument(document.workspace_id, file, document.id);
      return saved.id;
    },
    onSuccess: (newId) => {
      onConverted(newId);
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-lg border border-neutral-200 bg-white p-5 shadow-lg">
        <h3 className="text-base font-semibold text-neutral-900">Convert to Word</h3>
        <p className="mt-2 text-sm text-neutral-600">
          {document.text_source === "scanned" || document.text_source === "mixed"
            ? "Scanned PDFs are rebuilt as an editable structured document from OCR chunks."
            : "Digital PDFs are converted locally in your browser using LibreOffice WASM (formatting preserved)."}
        </p>
        {progress ? <p className="mt-3 text-xs text-neutral-500">{progress}</p> : null}
        {convert.isError ? (
          <p className="mt-2 text-sm text-red-600">
            {convert.error instanceof Error ? convert.error.message : "Conversion failed"}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={convert.isPending}>
            Cancel
          </Button>
          <Button onClick={() => convert.mutate()} disabled={convert.isPending}>
            {convert.isPending ? "Converting…" : "Convert"}
          </Button>
        </div>
      </div>
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/PageHeader";
import { PageShell } from "@/components/PageShell";
import { DocumentParseInfo, OcrServerBanner } from "@/components/DocumentParseInfo";
import { picardApi } from "@/lib/picardApi";
import { usePollingDocuments } from "@/components/vault/usePollingDocuments";

type Props = {
  workspaceId: string;
  workspaceName?: string;
};

export function VaultDocumentsPanel({ workspaceId, workspaceName }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const qc = useQueryClient();

  const { data: documents = [], isLoading } = usePollingDocuments(workspaceId);
  const { data: ocrHealth } = useQuery({
    queryKey: ["ocr-health"],
    queryFn: () => picardApi.getOcrHealth(),
    staleTime: 30_000,
  });

  const upload = useMutation({
    mutationFn: (file: File) => picardApi.uploadDocument(workspaceId, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents", workspaceId] }),
  });

  const retryAll = useMutation({
    mutationFn: () => picardApi.retryAllDocuments(workspaceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents", workspaceId] }),
  });

  const stuckCount = documents.filter(
    (d) => d.parse_status === "pending" || d.parse_status === "parsing" || d.parse_status === "error"
  ).length;

  const onFiles = useCallback(
    (files: FileList | null) => {
      if (!files?.length) return;
      Array.from(files).forEach((file) => {
        if (file.name.toLowerCase().endsWith(".pdf")) upload.mutate(file);
      });
    },
    [upload]
  );

  return (
    <PageShell maxWidth="4xl">
      <PageHeader
        title="Vault"
        subtitle={
          workspaceName
            ? `${workspaceName} — upload and manage PDFs for parsing and indexing.`
            : "Upload PDFs for parsing and indexing."
        }
      />

      {ocrHealth ? (
        <OcrServerBanner
          configured={ocrHealth.configured}
          reachable={ocrHealth.reachable}
          serverUrl={ocrHealth.server_url}
        />
      ) : null}

      <div
        className={`mb-8 rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
          dragOver ? "border-neutral-900 bg-neutral-50" : "border-neutral-300"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onFiles(e.dataTransfer.files);
        }}
      >
        <p className="mb-3 text-sm text-neutral-600">Drag and drop PDF files here</p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          multiple
          onChange={(e) => onFiles(e.target.files)}
        />
        <Button variant="outline" onClick={() => inputRef.current?.click()} disabled={upload.isPending}>
          Choose files
        </Button>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-neutral-600">
          {documents.length} document{documents.length === 1 ? "" : "s"}
        </p>
        {stuckCount > 0 ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => retryAll.mutate()}
            disabled={retryAll.isPending}
          >
            {retryAll.isPending ? "Retrying…" : `Retry all stuck (${stuckCount})`}
          </Button>
        ) : null}
      </div>

      <div className="overflow-hidden rounded border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-left text-neutral-600">
            <tr>
              <th className="px-4 py-2 font-medium">Document</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Source</th>
              <th className="px-4 py-2 font-medium">Pages</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-neutral-500">
                  Loading…
                </td>
              </tr>
            ) : (
              documents.map((doc) => (
                <tr key={doc.id} className="border-t border-neutral-100">
                  <td className="px-4 py-3">
                    {doc.parse_status === "done" ? (
                      <Link
                        href={`/vault/${doc.id}`}
                        className="font-medium text-neutral-900 hover:underline"
                      >
                        {doc.file_name}
                      </Link>
                    ) : (
                      doc.file_name
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={doc.parse_status} />
                    {doc.parse_error ? (
                      <p className="mt-1 text-xs text-red-600">{doc.parse_error}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    {doc.parse_status === "done" || doc.text_source ? (
                      <DocumentParseInfo textSource={doc.text_source} ocrEngine={doc.ocr_engine} />
                    ) : (
                      <span className="text-xs text-neutral-400">
                        {doc.parse_status === "parsing" ? "Analyzing…" : "—"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">{doc.page_count ?? "—"}</td>
                </tr>
              ))
            )}
            {!isLoading && documents.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-neutral-500">
                  No documents uploaded.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </PageShell>
  );
}

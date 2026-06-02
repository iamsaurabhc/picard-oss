"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import type { TabularReviewSummary } from "@/lib/picardApi";
import { picardApi } from "@/lib/picardApi";
import { PageHeader } from "@/components/PageHeader";
import { PageShell } from "@/components/PageShell";
import { Button } from "@/components/ui/button";
import { AddNewTRModal } from "@/components/tabular/AddNewTRModal";
import { DeleteReviewDialog } from "@/components/tabular/DeleteReviewDialog";

export default function TabularListPage() {
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;
  const router = useRouter();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TabularReviewSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const { data: workspace } = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () => picardApi.getWorkspace(workspaceId),
  });

  const { data: reviews = [], isLoading } = useQuery({
    queryKey: ["tabular-reviews", workspaceId],
    queryFn: () => picardApi.listTabularReviews(workspaceId),
  });

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await picardApi.deleteTabularReview(deleteTarget.id);
      setDeleteTarget(null);
      await qc.invalidateQueries({ queryKey: ["tabular-reviews", workspaceId] });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <PageShell maxWidth="4xl">
      <PageHeader
        title="Tabular reviews"
        subtitle={workspace?.name ?? "Workspace"}
        actions={
          <Button onClick={() => setModalOpen(true)}>
            <Plus className="mr-1 h-4 w-4" />
            New review
          </Button>
        }
      />
      <p className="mb-4 text-sm text-neutral-600">
        <Link href={`/workspaces/${workspaceId}`} className="text-blue-600 hover:underline">
          ← Back to documents
        </Link>
      </p>

      <div className="overflow-hidden rounded border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-left text-neutral-600">
            <tr>
              <th className="px-4 py-2 font-medium">Title</th>
              <th className="px-4 py-2 font-medium">Columns</th>
              <th className="px-4 py-2 font-medium">Documents</th>
              <th className="px-4 py-2 font-medium">Created</th>
              <th className="px-4 py-2 font-medium w-24" />
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-neutral-500">
                  Loading…
                </td>
              </tr>
            ) : (
              reviews.map((r) => (
                <tr key={r.id} className="border-t border-neutral-100">
                  <td className="px-4 py-3">
                    <Link
                      href={`/workspaces/${workspaceId}/tabular/${r.id}`}
                      className="font-medium text-neutral-900 hover:underline"
                    >
                      {r.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{r.column_count}</td>
                  <td className="px-4 py-3">{r.document_count}</td>
                  <td className="px-4 py-3 text-neutral-500">
                    {new Date(r.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                      onClick={(e) => {
                        e.preventDefault();
                        setDeleteTarget(r);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
            {!isLoading && reviews.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-neutral-500">
                  No tabular reviews yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <AddNewTRModal
        open={modalOpen}
        workspaceId={workspaceId}
        onClose={() => setModalOpen(false)}
        onCreated={(id) => router.push(`/workspaces/${workspaceId}/tabular/${id}`)}
      />

      <DeleteReviewDialog
        open={deleteTarget != null}
        title={deleteTarget?.title ?? ""}
        deleting={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </PageShell>
  );
}

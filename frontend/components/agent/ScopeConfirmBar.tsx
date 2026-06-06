"use client";

import { Button } from "@/components/ui/button";
import type { PendingApproval } from "./useAgentActivity";

type Props = {
  approval: PendingApproval;
  onApprove: () => void;
  onDeny: () => void;
};

export function ScopeConfirmBar({ approval, onApprove, onDeny }: Props) {
  if (approval.kind !== "scope") return null;
  const count = approval.document_ids?.length ?? 0;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
      <span>
        Confirm document scope ({count} document{count === 1 ? "" : "s"}) before corpus tools run?
      </span>
      <Button type="button" size="sm" variant="default" onClick={onApprove}>
        Approve scope
      </Button>
      <Button type="button" size="sm" variant="outline" onClick={onDeny}>
        Deny
      </Button>
    </div>
  );
}

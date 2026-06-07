"use client";

import type { ComposerMode } from "@/lib/unifiedChatTypes";
import type { TabularTemplateId } from "@/lib/tabular/columnPresets";
import { DocumentScopePill, type DocumentOption } from "./DocumentScopePill";
import { ReviewTemplatePill } from "./ReviewTemplatePill";

type Props = {
  mode: ComposerMode;
  documents: DocumentOption[];
  documentIds: string[];
  onDocumentIdsChange: (ids: string[]) => void;
  templateId: TabularTemplateId;
  onTemplateIdChange: (id: TabularTemplateId) => void;
  vaultOpenRequest?: boolean;
  onVaultOpenHandled?: () => void;
  disabled?: boolean;
};

export function ComposerScopeBar({
  mode,
  documents,
  documentIds,
  onDocumentIdsChange,
  templateId,
  onTemplateIdChange,
  vaultOpenRequest,
  onVaultOpenHandled,
  disabled,
}: Props) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 px-1">
      <DocumentScopePill
        documents={documents}
        selectedIds={documentIds}
        onChange={onDocumentIdsChange}
        openRequested={vaultOpenRequest}
        onOpenHandled={onVaultOpenHandled}
        disabled={disabled}
      />
      {mode === "review" ? (
        <ReviewTemplatePill
          templateId={templateId}
          onChange={onTemplateIdChange}
          disabled={disabled}
        />
      ) : null}
    </div>
  );
}

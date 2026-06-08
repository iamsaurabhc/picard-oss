"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  SuperDocEditor,
  type DocumentMode,
  type SuperDocInstance,
  type SuperDocRef,
} from "@superdoc-dev/react";
import "@superdoc-dev/react/style.css";
import { Loader2, MessageSquare, PanelRightClose, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { applyDocxSuggestion } from "@/lib/docxSuggestions";
import { subscribeDocxSuggestions } from "@/lib/docxSuggestionStore";
import { documentFileUrl } from "@/lib/picardApi";
import type { DocxSuggestion } from "@/lib/picardApi";
import { cn } from "@/lib/utils";

const MODES: { value: DocumentMode; label: string; hint: string }[] = [
  { value: "viewing", label: "View", hint: "Read-only document view" },
  { value: "editing", label: "Edit", hint: "Direct edits in Word editor" },
  { value: "suggesting", label: "Review", hint: "Tracked changes" },
];

const ZOOM_STEP = 10;
const ZOOM_MIN = 25;
const ZOOM_MAX = 300;

/** Shared mode ref so stable module config can gate comment permissions by tab. */
const docxViewerModeRef: { current: DocumentMode } = { current: "viewing" };

const COMMENT_WRITE_PERMISSIONS = new Set([
  "comment.create",
  "comment.edit",
  "comment.reply",
  "comment.update",
  "comment.delete",
]);

/**
 * Stable editor role — SuperDoc blocks `addCommentsList` when role is `viewer`, which
 * prevents imported DOCX comments from appearing in the sidebar. Document editability
 * is controlled by `documentMode`; comment writes are gated separately below.
 */
const SUPERDOC_ROLE = "editor" as const;

/** Stable SuperDoc config — new object references trigger a full editor rebuild. */
const SUPERDOC_MODULES = {
  trackChanges: { visible: true },
  toolbar: { responsiveToContainer: true },
  comments: {
    allowResolve: true,
    readOnly: true,
    showResolved: true,
    permissionResolver: ({ permission }: { permission: string }) => {
      if (docxViewerModeRef.current !== "suggesting" && COMMENT_WRITE_PERMISSIONS.has(permission)) {
        return false;
      }
      return undefined;
    },
  },
} as const;
const SUPERDOC_FONTS = { assetBaseUrl: "/fonts/" } as const;
const SUPERDOC_USER = { name: "Picard User", email: "user@picard.local" } as const;
const SUPERDOC_VIEWING_COMMENTS = { visible: true } as const;

type VueRef<T> = { value: T };

type SuperDocCommentsStore = {
  init: (config: { readOnly?: boolean; showResolved?: boolean }) => void;
  setViewingVisibility?: (config: {
    documentMode?: DocumentMode;
    commentsVisible?: boolean;
    trackChangesVisible?: boolean;
  }) => void;
  commentsList?: unknown[] | VueRef<unknown[]>;
  getGroupedComments?: VueRef<{ parentComments: unknown[]; resolvedComments: unknown[] }>;
};

type SuperDocCommentsInternals = {
  commentsStore?: SuperDocCommentsStore;
  commentsList?: unknown;
  config?: { role?: string };
};

function getCommentsInternals(instance: SuperDocInstance): SuperDocCommentsInternals {
  return instance as unknown as SuperDocCommentsInternals;
}

function unwrapVueRef<T>(refOrValue: T | VueRef<T> | undefined): T | undefined {
  if (refOrValue && typeof refOrValue === "object" && "value" in refOrValue) {
    return (refOrValue as VueRef<T>).value;
  }
  return refOrValue as T | undefined;
}

function syncCommentsReadOnly(instance: SuperDocInstance | null, mode: DocumentMode) {
  if (!instance) return;
  const readOnly = mode !== "suggesting";
  const store = getCommentsInternals(instance).commentsStore;
  store?.init({ readOnly, showResolved: true });
  store?.setViewingVisibility?.({
    documentMode: mode,
    commentsVisible: true,
    trackChangesVisible: true,
  });
}

function countDocumentComments(instance: SuperDocInstance | null): number {
  if (!instance) return 0;
  const store = getCommentsInternals(instance).commentsStore;
  if (!store) return 0;

  const grouped = unwrapVueRef(store.getGroupedComments);
  if (grouped) {
    return grouped.parentComments.length + grouped.resolvedComments.length;
  }

  const list = unwrapVueRef(store.commentsList);
  return Array.isArray(list) ? list.length : 0;
}

function commentsListMounted(instance: SuperDocInstance): boolean {
  return Boolean(getCommentsInternals(instance).commentsList);
}

function clampZoom(percent: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(percent)));
}

type Props = {
  documentId: string;
  fileName?: string;
  mode?: DocumentMode;
  onModeChange?: (mode: DocumentMode) => void;
  onSave?: (buffer: ArrayBuffer) => Promise<void>;
  saving?: boolean;
};

export function DocxPageViewer({
  documentId,
  fileName,
  mode: controlledMode,
  onModeChange,
  onSave,
  saving,
}: Props) {
  const editorRef = useRef<SuperDocRef>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const commentsPanelRef = useRef<HTMLDivElement>(null);
  const commentsListMountedRef = useRef(false);
  const autoOpenedCommentsRef = useRef(false);
  const modeRef = useRef<DocumentMode>("viewing");
  const initialZoomDoneRef = useRef(false);
  const [buffer, setBuffer] = useState<ArrayBuffer | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editorReady, setEditorReady] = useState(false);
  const [internalMode, setInternalMode] = useState<DocumentMode>("viewing");
  const [pendingSuggestion, setPendingSuggestion] = useState<DocxSuggestion | null>(null);
  const [applyingSuggestion, setApplyingSuggestion] = useState(false);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [commentCount, setCommentCount] = useState(0);

  const mode = controlledMode ?? internalMode;
  modeRef.current = mode;
  docxViewerModeRef.current = mode;

  const setMode = useCallback(
    (next: DocumentMode) => {
      if (controlledMode === undefined) setInternalMode(next);
      onModeChange?.(next);
    },
    [controlledMode, onModeChange]
  );

  const docxFile = useMemo(() => {
    if (!buffer) return null;
    const name = fileName ?? "document.docx";
    return new File([buffer], name, {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
  }, [buffer, fileName]);

  const applyZoom = useCallback((percent: number) => {
    const instance = editorRef.current?.getInstance();
    if (!instance) return;
    const next = clampZoom(percent);
    instance.setZoom(next);
    setZoomPercent(next);
  }, []);

  const fitZoomToWidth = useCallback(() => {
    const instance = editorRef.current?.getInstance();
    const host = hostRef.current;
    if (!instance || !host) return;

    const pageEl = host.querySelector<HTMLElement>("[data-page], .superdoc-page, .sd-page");
    if (!pageEl) return;

    const hostWidth = host.clientWidth - 48;
    const pageWidth = pageEl.offsetWidth || pageEl.getBoundingClientRect().width;
    if (pageWidth <= 0 || hostWidth <= 0) return;

    const current = instance.getZoom() || 100;
    const unscaledWidth = pageWidth / (current / 100);
    const fit = clampZoom((hostWidth / unscaledWidth) * 100);
    applyZoom(fit);
  }, [applyZoom]);

  useEffect(() => {
    let cancelled = false;
    setBuffer(null);
    setLoadError(null);
    setEditorReady(false);
    setZoomPercent(100);
    setCommentsOpen(false);
    setCommentCount(0);
    initialZoomDoneRef.current = false;
    commentsListMountedRef.current = false;
    autoOpenedCommentsRef.current = false;

    (async () => {
      try {
        const res = await fetch(documentFileUrl(documentId));
        if (!res.ok) throw new Error(await res.text());
        const data = await res.arrayBuffer();
        if (!cancelled) setBuffer(data);
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Failed to load document");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [documentId]);

  useEffect(() => {
    return subscribeDocxSuggestions((suggestion) => {
      if (suggestion.document_id !== documentId) return;
      setPendingSuggestion(suggestion);
      if (modeRef.current === "viewing") setMode("suggesting");
    });
  }, [documentId, setMode]);

  const handleSave = useCallback(async () => {
    const instance = editorRef.current?.getInstance();
    if (!instance) return;
    const blob = await instance.export({ isFinalDoc: true });
    const saved = await blob.arrayBuffer();
    if (onSave) await onSave(saved);
    setBuffer(saved);
  }, [onSave]);

  const handleApplySuggestion = useCallback(async () => {
    if (!pendingSuggestion) return;
    setApplyingSuggestion(true);
    try {
      const instance = editorRef.current?.getInstance() ?? null;
      const applied = await applyDocxSuggestion(instance, pendingSuggestion);
      if (!applied) {
        setLoadError("Could not locate text for the suggested edit");
        return;
      }
      setPendingSuggestion(null);
      if (modeRef.current === "viewing") setMode("suggesting");
    } finally {
      setApplyingSuggestion(false);
    }
  }, [pendingSuggestion, setMode]);

  const refreshCommentCount = useCallback(() => {
    const instance = editorRef.current?.getInstance() ?? null;
    setCommentCount(countDocumentComments(instance));
  }, []);

  const mountCommentsList = useCallback(() => {
    const instance = editorRef.current?.getInstance();
    const panel = commentsPanelRef.current;
    if (!instance || !panel) return;

    const internals = getCommentsInternals(instance);
    if (internals.config?.role === "viewer") return;

    if (!commentsListMounted(instance)) {
      instance.addCommentsList(panel);
    }
    commentsListMountedRef.current = commentsListMounted(instance);
  }, []);

  const handleCommentsUpdate = useCallback(() => {
    mountCommentsList();
    refreshCommentCount();

    const instance = editorRef.current?.getInstance() ?? null;
    const count = countDocumentComments(instance);
    if (count > 0 && !autoOpenedCommentsRef.current) {
      autoOpenedCommentsRef.current = true;
      setCommentsOpen(true);
    }
  }, [mountCommentsList, refreshCommentCount]);

  const handleEditorReady = useCallback(() => {
    setEditorReady(true);
    const instance = editorRef.current?.getInstance();
    if (!instance) return;

    syncCommentsReadOnly(instance, modeRef.current);
    mountCommentsList();
    refreshCommentCount();

    if (initialZoomDoneRef.current) return;
    initialZoomDoneRef.current = true;
    setZoomPercent(instance.getZoom() || 100);
  }, [mountCommentsList, refreshCommentCount]);

  useEffect(() => {
    if (!editorReady) return;
    const instance = editorRef.current?.getInstance() ?? null;
    syncCommentsReadOnly(instance, mode);
  }, [editorReady, mode]);

  useEffect(() => {
    if (!editorReady || !commentsOpen) return;
    mountCommentsList();
  }, [commentsOpen, editorReady, mountCommentsList]);

  useEffect(() => {
    return () => {
      const instance = editorRef.current?.getInstance();
      if (instance && commentsListMountedRef.current) {
        instance.removeCommentsList();
        commentsListMountedRef.current = false;
      }
    };
  }, [documentId]);

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-red-600">{loadError}</div>
    );
  }

  if (!buffer || !docxFile) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-neutral-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading document…
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-neutral-200 bg-white px-3 py-2">
        <div className="flex items-center gap-0.5 rounded-md border border-neutral-200 bg-neutral-50 p-0.5">
          {MODES.map((item) => (
            <button
              key={item.value}
              type="button"
              title={item.hint}
              onClick={() => setMode(item.value)}
              className={cn(
                "rounded px-3 py-1 text-xs font-medium transition-colors",
                mode === item.value
                  ? "bg-white text-neutral-900 shadow-sm"
                  : "text-neutral-600 hover:text-neutral-900"
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 rounded-md border border-neutral-200 bg-neutral-50 px-1 py-0.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 w-7 border-0 bg-transparent p-0 shadow-none"
            title="Zoom out"
            disabled={!editorReady || zoomPercent <= ZOOM_MIN}
            onClick={() => applyZoom(zoomPercent - ZOOM_STEP)}
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </Button>
          <button
            type="button"
            className="min-w-[3.25rem] px-1 text-center text-xs font-medium text-neutral-700"
            title="Reset zoom to 100%"
            disabled={!editorReady}
            onClick={() => applyZoom(100)}
          >
            {zoomPercent}%
          </button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 w-7 border-0 bg-transparent p-0 shadow-none"
            title="Zoom in"
            disabled={!editorReady || zoomPercent >= ZOOM_MAX}
            onClick={() => applyZoom(zoomPercent + ZOOM_STEP)}
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 border-0 bg-transparent px-2 text-xs shadow-none"
            title="Fit document to panel width"
            disabled={!editorReady}
            onClick={() => fitZoomToWidth()}
          >
            Fit
          </Button>
        </div>

        <Button
          type="button"
          size="sm"
          variant="outline"
          className={cn(
            "h-7 gap-1.5 px-2 text-xs shadow-none",
            commentsOpen ? "border-neutral-300 bg-neutral-100" : "border-neutral-200 bg-neutral-50"
          )}
          title={commentsOpen ? "Hide comments" : "Show all comments"}
          disabled={!editorReady}
          onClick={() => setCommentsOpen((open) => !open)}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Comments
          {commentCount > 0 ? (
            <span className="rounded-full bg-neutral-200 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-neutral-700">
              {commentCount}
            </span>
          ) : null}
        </Button>

        {onSave ? (
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => void handleSave()}
            disabled={saving || mode === "viewing"}
          >
            {saving ? "Saving…" : "Save & re-index"}
          </Button>
        ) : null}
      </div>

      {pendingSuggestion ? (
        <div className="flex shrink-0 items-start gap-3 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
          <div className="min-w-0 flex-1">
            <p className="font-medium">Suggested edit from chat</p>
            <p className="mt-0.5 truncate">
              Replace &ldquo;{pendingSuggestion.find}&rdquo; → &ldquo;{pendingSuggestion.replace}&rdquo;
            </p>
            {pendingSuggestion.rationale ? (
              <p className="mt-1 text-amber-800">{pendingSuggestion.rationale}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPendingSuggestion(null)}
              disabled={applyingSuggestion}
            >
              Dismiss
            </Button>
            <Button size="sm" onClick={() => void handleApplySuggestion()} disabled={applyingSuggestion}>
              {applyingSuggestion ? "Applying…" : "Apply as tracked change"}
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex min-h-0 w-full flex-1">
        <div ref={hostRef} className="docx-superdoc-host min-h-0 min-w-0 flex-1">
          <SuperDocEditor
            key={documentId}
            ref={editorRef}
            document={docxFile}
            documentMode={mode}
            role={SUPERDOC_ROLE}
            user={SUPERDOC_USER}
            fonts={SUPERDOC_FONTS}
            comments={SUPERDOC_VIEWING_COMMENTS}
            contained
            className="h-full w-full"
            style={{ height: "100%", width: "100%" }}
            modules={SUPERDOC_MODULES}
            onReady={handleEditorReady}
            onCommentsUpdate={handleCommentsUpdate}
            onContentError={(event) => {
              const message =
                event.error instanceof Error ? event.error.message : "Failed to load document";
              setLoadError(message);
            }}
          />
        </div>

        <aside
          className={cn(
            "docx-comments-panel flex shrink-0 flex-col border-neutral-200 bg-white transition-[width] duration-200 ease-out",
            commentsOpen ? "w-72 border-l" : "w-0 overflow-hidden border-l-0"
          )}
          aria-hidden={!commentsOpen}
        >
          <div className="flex shrink-0 items-center justify-between border-b border-neutral-200 px-3 py-2">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-neutral-900">Comments</p>
              {mode !== "suggesting" ? (
                <p className="text-[11px] text-neutral-500">View only — use Review to add or edit</p>
              ) : (
                <p className="text-[11px] text-neutral-500">Add and edit comments in Review mode</p>
              )}
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 w-7 shrink-0 border-0 bg-transparent p-0 shadow-none"
              title="Close comments panel"
              onClick={() => setCommentsOpen(false)}
            >
              <PanelRightClose className="h-4 w-4" />
            </Button>
          </div>
          <div ref={commentsPanelRef} className="min-h-0 flex-1 overflow-y-auto" />
        </aside>
      </div>
    </div>
  );
}

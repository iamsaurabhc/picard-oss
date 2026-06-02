"use client";

import { useCallback, useMemo, useState } from "react";
import type { ChatStreamEvent } from "@/lib/picardApi";

export type ActivityPhaseStep = {
  kind: "phase";
  id: string;
  phase: string;
  label: string;
  status: "active" | "done";
  detail?: string;
};

export type ActivitySnippetStep = {
  kind: "snippet";
  id: string;
  document_name: string;
  page_number: number;
  text: string;
  source: string;
};

export type ActivityStep = ActivityPhaseStep | ActivitySnippetStep;

export type RetrievalSummary = {
  chunk_count: number;
  bundle_count: number;
  refused: boolean;
  mode: string;
};

function phaseLabel(ev: Extract<ChatStreamEvent, { event: "progress" }>): string {
  const { phase, status, label, intent, pass_count, strategy, hit_count, ranked_count } = ev;

  if (phase === "understanding") {
    if (status === "start") return "Understanding your question";
    const parts = [intent?.replace(/_/g, " ") ?? "query"];
    if (pass_count != null) parts.push(`${pass_count} search pass${pass_count === 1 ? "" : "es"}`);
    if (ev.mode) parts.push(String(ev.mode).toLowerCase());
    return `Understood: ${parts.join(" · ")}`;
  }

  if (phase === "search") {
    if (status === "start") {
      if (label === "per_document" && ev.document_name) {
        return `Searching ${ev.document_name}`;
      }
      if (label === "document_discovery") return "Discovering documents";
      if (label === "carp_intersection") return "Matching constraints across pages";
      if (label) return `Searching: ${label.replace(/_/g, " ")}`;
      if (strategy === "carp") return "Running constraint-aware retrieval";
      return "Searching documents";
    }
    if (label === "per_document" && ev.document_name) {
      const count = hit_count != null ? ` (${hit_count} hit${hit_count === 1 ? "" : "s"})` : "";
      return `Searched ${ev.document_name}${count}`;
    }
    if (label === "document_discovery" && ev.documents_discovered != null) {
      return `Found ${ev.documents_discovered} document${ev.documents_discovered === 1 ? "" : "s"}`;
    }
    if (label === "carp_intersection" && ev.intersection_pages != null) {
      return `Intersection: ${ev.intersection_pages} page${ev.intersection_pages === 1 ? "" : "s"}`;
    }
    if (label && hit_count != null) {
      return `${label.replace(/_/g, " ")}: ${hit_count} hit${hit_count === 1 ? "" : "s"}`;
    }
    if (hit_count != null) {
      return `Retrieved ${hit_count} candidate chunk${hit_count === 1 ? "" : "s"}`;
    }
    return "Search complete";
  }

  if (phase === "rank") {
    if (status === "start") return "Ranking evidence";
    if (ranked_count != null) {
      return `Selected ${ranked_count} chunk${ranked_count === 1 ? "" : "s"} for context`;
    }
    return "Ranking complete";
  }

  if (phase === "generate") {
    return status === "start" ? "Generating answer" : "Answer ready";
  }

  return `${phase} ${status}`;
}

function phaseStepId(ev: Extract<ChatStreamEvent, { event: "progress" }>): string {
  const base = `${ev.phase}:${ev.label ?? "default"}:${ev.status}`;
  if (ev.label === "per_document" && ev.document_id) {
    return `${base}:${ev.document_id}`;
  }
  return base;
}

export function useRetrievalActivity() {
  const [steps, setSteps] = useState<ActivityStep[]>([]);
  const [isActive, setIsActive] = useState(false);
  const [hasContentStarted, setHasContentStarted] = useState(false);
  const [retrievalSummary, setRetrievalSummary] = useState<RetrievalSummary | null>(null);

  const reset = useCallback(() => {
    setSteps([]);
    setIsActive(false);
    setHasContentStarted(false);
    setRetrievalSummary(null);
  }, []);

  const start = useCallback(() => {
    setIsActive(true);
    setHasContentStarted(false);
    setRetrievalSummary(null);
  }, []);

  const finish = useCallback(() => {
    setIsActive(false);
    setSteps((prev) =>
      prev.map((step) =>
        step.kind === "phase" && step.status === "active"
          ? { ...step, status: "done" as const }
          : step
      )
    );
  }, []);

  const markContentStarted = useCallback(() => {
    setHasContentStarted(true);
  }, []);

  const ingestEvent = useCallback((ev: ChatStreamEvent) => {
    if (ev.event === "progress") {
      const id = phaseStepId(ev);
      const label = phaseLabel(ev);
      setSteps((prev) => {
        // #region agent log
        if (ev.label === "per_document") {
          const dupCount = prev.filter((s) => s.kind === "phase" && s.id === id).length;
          fetch("http://127.0.0.1:7942/ingest/fc646775-8de3-41b6-b910-39cf0cc7992b", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "755b1b" },
            body: JSON.stringify({
              sessionId: "755b1b",
              location: "useRetrievalActivity.ts:setSteps",
              message: "per_document progress event",
              data: {
                id,
                status: ev.status,
                document_id: ev.document_id,
                document_name: ev.document_name,
                existingDupCount: dupCount,
              },
              timestamp: Date.now(),
              hypothesisId: "H1",
            }),
          }).catch(() => {});
        }
        // #endregion
        if (ev.status === "start") {
          const withoutDup = prev.filter((s) => !(s.kind === "phase" && s.id === id));
          return [
            ...withoutDup,
            {
              kind: "phase" as const,
              id,
              phase: ev.phase,
              label,
              status: "active" as const,
            },
          ];
        }
        const doneId = phaseStepId({ ...ev, status: "done" });
        const startId = phaseStepId({ ...ev, status: "start" });
        const doneLabel = phaseLabel(ev);
        let updated = prev.map((step) => {
          if (step.kind === "phase" && (step.id === startId || step.id === id)) {
            return {
              ...step,
              id: doneId,
              label: doneLabel,
              status: "done" as const,
            };
          }
          return step;
        });
        if (!updated.some((s) => s.kind === "phase" && s.id === doneId)) {
          updated = [
            ...updated,
            {
              kind: "phase" as const,
              id: doneId,
              phase: ev.phase,
              label: doneLabel,
              status: "done" as const,
            },
          ];
        }
        return updated;
      });
      return;
    }

    if (ev.event === "snippet") {
      setSteps((prev) => {
        if (prev.some((s) => s.kind === "snippet" && s.id === ev.chunk_id)) {
          return prev;
        }
        return [
          ...prev,
          {
            kind: "snippet" as const,
            id: ev.chunk_id,
            document_name: ev.document_name,
            page_number: ev.page_number,
            text: ev.text,
            source: ev.source,
          },
        ];
      });
      return;
    }

    if (ev.event === "retrieval") {
      setRetrievalSummary({
        chunk_count: ev.chunk_count,
        bundle_count: ev.bundle_count,
        refused: ev.refused,
        mode: ev.mode,
      });
      return;
    }

    if (ev.event === "content" && ev.delta) {
      setHasContentStarted(true);
    }
  }, []);

  const stepCount = useMemo(
    () => steps.filter((s) => s.kind === "phase" && s.status === "done").length,
    [steps]
  );

  return {
    steps,
    stepCount,
    isActive,
    hasContentStarted,
    shouldMinimize: hasContentStarted,
    retrievalSummary,
    reset,
    start,
    finish,
    markContentStarted,
    ingestEvent,
  };
}

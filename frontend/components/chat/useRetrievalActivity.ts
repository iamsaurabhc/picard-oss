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

  if (phase === "page_rank") {
    if (status === "start" && ev.document_name) {
      return `Ranking pages in ${ev.document_name}`;
    }
    const pages = (ev as { pages_selected?: number[] }).pages_selected;
    if (status === "done" && pages != null) {
      const n = pages.length;
      return `Selected ${n} page${n === 1 ? "" : "s"}${ev.document_name ? ` in ${ev.document_name}` : ""}`;
    }
    return status === "start" ? "Ranking pages" : "Page ranking complete";
  }

  if (phase === "coverage") {
    if (status === "start") return "Building context coverage";
    const chunks = (ev as { chunk_count?: number }).chunk_count;
    if (chunks != null) return `Context ready (${chunks} chunk${chunks === 1 ? "" : "s"})`;
    return "Coverage complete";
  }

  if (phase === "map") {
    if (status === "start") {
      if (ev.document_name) return `Mapping ${ev.document_name}`;
      if (ev.documents_to_map != null) {
        return `Mapping per-document briefs (${ev.documents_to_map} document${ev.documents_to_map === 1 ? "" : "s"})`;
      }
      return "Mapping per-document briefs";
    }
    if (ev.document_name) {
      const chunks = (ev as { chunk_count?: number }).chunk_count;
      const suffix =
        chunks != null ? ` (${chunks} chunk${chunks === 1 ? "" : "s"})` : "";
      return `Mapped ${ev.document_name}${suffix}`;
    }
    if ((ev as { brief_count?: number }).brief_count != null) {
      const n = (ev as { brief_count: number }).brief_count;
      return `Map phase complete (${n} brief${n === 1 ? "" : "s"})`;
    }
    return "Map phase complete";
  }

  if (phase === "reduce") {
    return status === "start" ? "Synthesizing catalog" : "Reduce complete";
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
  const docId = ev.document_id;
  if (
    docId &&
    (ev.label === "per_document" || ev.phase === "page_rank" || ev.phase === "map")
  ) {
    return `${base}:${docId}`;
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

  const shouldMinimize = hasContentStarted || stepCount >= 8;

  return {
    steps,
    stepCount,
    isActive,
    hasContentStarted,
    shouldMinimize,
    retrievalSummary,
    reset,
    start,
    finish,
    markContentStarted,
    ingestEvent,
  };
}

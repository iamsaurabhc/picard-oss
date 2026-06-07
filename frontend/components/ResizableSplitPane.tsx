"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type Direction = "horizontal" | "vertical";

type Props = {
  direction: Direction;
  initialRatio: number;
  minPrimary?: number;
  minSecondary?: number;
  storageKey?: string;
  className?: string;
  primary: React.ReactNode;
  secondary: React.ReactNode;
};

function readStoredRatio(key: string | undefined, fallback: number): number {
  if (!key || typeof window === "undefined") return fallback;
  try {
    const stored = localStorage.getItem(key);
    if (stored != null) {
      const parsed = parseFloat(stored);
      if (!Number.isNaN(parsed) && parsed > 0.1 && parsed < 0.9) return parsed;
    }
  } catch {
    // ignore
  }
  return fallback;
}

export function ResizableSplitPane({
  direction,
  initialRatio,
  minPrimary = 200,
  minSecondary = 200,
  storageKey,
  className,
  primary,
  secondary,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState(() => readStoredRatio(storageKey, initialRatio));
  const ratioRef = useRef(ratio);
  const dragging = useRef(false);

  useEffect(() => {
    ratioRef.current = ratio;
  }, [ratio]);

  useEffect(() => {
    setRatio(readStoredRatio(storageKey, initialRatio));
  }, [storageKey, initialRatio]);

  const clampRatio = useCallback(
    (next: number) => {
      const el = containerRef.current;
      if (!el) return Math.min(0.85, Math.max(0.15, next));
      const total =
        direction === "horizontal" ? el.clientWidth : el.clientHeight;
      if (total <= 0) return next;
      const minPrimaryRatio = minPrimary / total;
      const minSecondaryRatio = minSecondary / total;
      return Math.min(1 - minSecondaryRatio, Math.max(minPrimaryRatio, next));
    },
    [direction, minPrimary, minSecondary]
  );

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    let next: number;
    if (direction === "horizontal") {
      next = (e.clientX - rect.left) / rect.width;
    } else {
      next = (e.clientY - rect.top) / rect.height;
    }
    setRatio(clampRatio(next));
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    dragging.current = false;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    if (storageKey) {
      try {
        localStorage.setItem(storageKey, String(ratioRef.current));
      } catch {
        // ignore
      }
    }
  };

  const isHorizontal = direction === "horizontal";
  const primarySize = `${ratio * 100}%`;
  const secondarySize = `${(1 - ratio) * 100}%`;

  return (
    <div
      ref={containerRef}
      className={cn(
        "flex min-h-0 min-w-0 flex-1 overflow-hidden",
        isHorizontal ? "flex-row" : "flex-col",
        className
      )}
    >
      <div
        className="min-h-0 min-w-0 overflow-hidden"
        style={isHorizontal ? { width: primarySize } : { height: primarySize }}
      >
        {primary}
      </div>

      <div
        role="separator"
        aria-orientation={isHorizontal ? "vertical" : "horizontal"}
        aria-label="Resize panels"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className={cn(
          "group relative z-10 shrink-0 bg-neutral-200 hover:bg-neutral-300",
          isHorizontal ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize"
        )}
      >
        <div
          className={cn(
            "absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-neutral-400 opacity-0 transition-opacity group-hover:opacity-100",
            isHorizontal ? "h-8 w-1" : "h-1 w-8"
          )}
        />
      </div>

      <div
        className="min-h-0 min-w-0 overflow-hidden"
        style={isHorizontal ? { width: secondarySize } : { height: secondarySize }}
      >
        {secondary}
      </div>
    </div>
  );
}

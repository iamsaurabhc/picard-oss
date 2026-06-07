"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function formatDuration(ms: number): string {
  if (ms < 60000) {
    const seconds = ms / 1000;
    return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function useRequestTimer() {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [running, setRunning] = useState(false);
  const startRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTick = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const start = useCallback(() => {
    clearTick();
    startRef.current = Date.now();
    setElapsedMs(0);
    setRunning(true);
    intervalRef.current = setInterval(() => {
      if (startRef.current != null) {
        setElapsedMs(Date.now() - startRef.current);
      }
    }, 100);
  }, [clearTick]);

  const stop = useCallback(() => {
    clearTick();
    if (startRef.current != null) {
      setElapsedMs(Date.now() - startRef.current);
      startRef.current = null;
    }
    setRunning(false);
  }, [clearTick]);

  const reset = useCallback(() => {
    clearTick();
    startRef.current = null;
    setElapsedMs(0);
    setRunning(false);
  }, [clearTick]);

  useEffect(() => () => clearTick(), [clearTick]);

  return { elapsedMs, running, start, stop, reset };
}

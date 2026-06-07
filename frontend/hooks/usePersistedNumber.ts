"use client";

import { useCallback, useEffect, useState } from "react";

export function usePersistedNumber(key: string, defaultValue: number) {
  const [value, setValue] = useState(defaultValue);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) {
        const parsed = parseFloat(stored);
        if (!Number.isNaN(parsed)) setValue(parsed);
      }
    } catch {
      // ignore
    }
    setHydrated(true);
  }, [key]);

  const setPersisted = useCallback(
    (next: number | ((prev: number) => number)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? next(prev) : next;
        try {
          localStorage.setItem(key, String(resolved));
        } catch {
          // ignore
        }
        return resolved;
      });
    },
    [key]
  );

  return [value, setPersisted, hydrated] as const;
}

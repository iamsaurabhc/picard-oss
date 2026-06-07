"use client";

import { useCallback, useEffect, useState } from "react";

export function usePersistedBoolean(key: string, defaultValue = false) {
  const [value, setValue] = useState(defaultValue);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) {
        setValue(stored === "true");
      }
    } catch {
      // ignore
    }
    setHydrated(true);
  }, [key]);

  const setPersisted = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
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

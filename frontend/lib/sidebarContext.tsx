"use client";

import { createContext, useContext, useMemo } from "react";
import { usePersistedBoolean } from "@/hooks/usePersistedBoolean";

type SidebarContextValue = {
  collapsed: boolean;
  setCollapsed: (value: boolean | ((prev: boolean) => boolean)) => void;
  hydrated: boolean;
};

const SidebarContext = createContext<SidebarContextValue | null>(null);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed, hydrated] = usePersistedBoolean("picard:sidebarCollapsed", false);

  const value = useMemo(
    () => ({ collapsed, setCollapsed, hydrated }),
    [collapsed, setCollapsed, hydrated]
  );

  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>;
}

export function useSidebar() {
  const ctx = useContext(SidebarContext);
  if (!ctx) {
    throw new Error("useSidebar must be used within SidebarProvider");
  }
  return ctx;
}

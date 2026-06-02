"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { picardApi, type Workspace } from "@/lib/picardApi";

const STORAGE_KEY = "picard:activeWorkspaceId";

type WorkspaceContextValue = {
  workspaceId: string | null;
  workspace: Workspace | null;
  workspaces: Workspace[];
  setWorkspaceId: (id: string | null) => void;
  isLoading: boolean;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [workspaceId, setWorkspaceIdState] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  const { data: workspaces = [], isLoading: listLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: picardApi.listWorkspaces,
  });

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) setWorkspaceIdState(stored);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated || listLoading) return;
    if (workspaceId && workspaces.some((w) => w.id === workspaceId)) return;
    if (workspaces.length > 0) {
      const next = workspaces[0].id;
      setWorkspaceIdState(next);
      localStorage.setItem(STORAGE_KEY, next);
    } else {
      setWorkspaceIdState(null);
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [hydrated, listLoading, workspaceId, workspaces]);

  const setWorkspaceId = useCallback(
    (id: string | null) => {
      setWorkspaceIdState(id);
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
      qc.invalidateQueries();
    },
    [qc]
  );

  const { data: workspace } = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () => picardApi.getWorkspace(workspaceId!),
    enabled: !!workspaceId,
  });

  const value = useMemo(
    () => ({
      workspaceId,
      workspace: workspace ?? null,
      workspaces,
      setWorkspaceId,
      isLoading: !hydrated || listLoading,
    }),
    [workspaceId, workspace, workspaces, setWorkspaceId, hydrated, listLoading]
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}

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
  isError: boolean;
  error: Error | null;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [workspaceId, setWorkspaceIdState] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  const {
    data: workspaces = [],
    isPending: listPending,
    isError: listError,
    error: listErrorDetail,
  } = useQuery({
    queryKey: ["workspaces"],
    queryFn: picardApi.listWorkspaces,
    staleTime: 60_000,
  });

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) setWorkspaceIdState(stored);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated || listPending) return;
    if (workspaceId && workspaces.some((w) => w.id === workspaceId)) return;
    if (workspaces.length > 0) {
      const next = workspaces[0].id;
      setWorkspaceIdState(next);
      localStorage.setItem(STORAGE_KEY, next);
    } else {
      setWorkspaceIdState(null);
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [hydrated, listPending, workspaceId, workspaces]);

  const setWorkspaceId = useCallback(
    (id: string | null) => {
      setWorkspaceIdState(id);
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
      // Keep the workspace list cached; refresh workspace-scoped data only.
      qc.invalidateQueries({
        predicate: (query) => query.queryKey[0] !== "workspaces",
      });
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
      isLoading: !hydrated || listPending,
      isError: listError,
      error: listErrorDetail instanceof Error ? listErrorDetail : null,
    }),
    [workspaceId, workspace, workspaces, setWorkspaceId, hydrated, listPending, listError, listErrorDetail]
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}

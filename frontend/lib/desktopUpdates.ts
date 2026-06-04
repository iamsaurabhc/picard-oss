/** Tauri desktop updater bridge (no-op in browser / Docker). */

export function isTauriDesktop(): boolean {
  if (typeof window === "undefined") return false;
  return "__TAURI_INTERNALS__" in window;
}

export type DesktopUpdateInfo = {
  version: string;
  currentVersion: string;
  notes?: string;
};

export async function checkDesktopUpdates(): Promise<DesktopUpdateInfo | null> {
  if (!isTauriDesktop()) return null;
  try {
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check();
    if (!update) return null;
    return {
      version: update.version,
      currentVersion: update.currentVersion,
      notes: update.body ?? undefined,
    };
  } catch {
    return null;
  }
}

export async function installDesktopUpdate(): Promise<void> {
  if (!isTauriDesktop()) return;
  const { check } = await import("@tauri-apps/plugin-updater");
  const update = await check();
  if (!update) return;
  await update.downloadAndInstall();
  // Restart the app to apply (macOS/Windows/Linux show a new build on next launch).
  if (typeof window !== "undefined") {
    window.location.reload();
  }
}

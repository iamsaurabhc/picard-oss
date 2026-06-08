"use client";

import { AppSidebar } from "@/components/app-sidebar";
import { SidebarProvider } from "@/lib/sidebarContext";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <div className="flex h-screen overflow-hidden">
        <AppSidebar />
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </SidebarProvider>
  );
}

"use client";

import { AppSidebar } from "@/components/app-sidebar";
import { SidebarProvider } from "@/lib/sidebarContext";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <div className="flex min-h-screen">
        <AppSidebar />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </SidebarProvider>
  );
}

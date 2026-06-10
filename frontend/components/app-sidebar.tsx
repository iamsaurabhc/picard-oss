"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Archive,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebar } from "@/lib/sidebarContext";
import { WorkspaceSelector } from "@/components/WorkspaceSelector";

const NAV = [
  { href: "/", label: "Chat", icon: MessageSquare, match: (p: string) => p === "/" },
  { href: "/vault", label: "Vault", icon: Archive, match: (p: string) => p.startsWith("/vault") },
] as const;

const BOTTOM_NAV = [
  { href: "/settings", label: "Settings", icon: Settings, match: (p: string) => p === "/settings" },
  {
    href: "/workspaces",
    label: "Manage workspaces",
    icon: Briefcase,
    match: (p: string) => p.startsWith("/workspaces"),
  },
] as const;

export function AppSidebar() {
  const pathname = usePathname();
  const { collapsed, setCollapsed, hydrated } = useSidebar();
  // Match SSR until localStorage is read — avoids collapsed-state hydration mismatch.
  const showCollapsed = hydrated && collapsed;

  return (
    <aside
      className={cn(
        "relative flex shrink-0 flex-col border-r border-neutral-200 bg-white p-3 transition-[width] duration-200 motion-reduce:transition-none",
        showCollapsed ? "w-14" : "w-56"
      )}
    >
      <Link
        href="/"
        className={cn("mb-3 flex items-center gap-2", showCollapsed && "justify-center")}
        title="Picard.Law OSS"
      >
        <Image src="/picard.svg" alt="Picard.Law OSS" width={28} height={28} className="shrink-0" />
        {!showCollapsed && (
          <span
            className="min-w-0 font-serif text-sm leading-tight text-neutral-900"
            style={{ fontFamily: "var(--font-garamond), serif" }}
          >
            Picard.Law OSS
          </span>
        )}
      </Link>

      <WorkspaceSelector collapsed={showCollapsed} />

      <nav className={cn("flex flex-col gap-1 text-sm", showCollapsed && "items-center")}>
        {NAV.map(({ href, label, icon: Icon, match }) => {
          const active = match(pathname);
          return (
            <Link
              key={href}
              href={href}
              title={showCollapsed ? label : undefined}
              aria-label={label}
              className={cn(
                "flex items-center rounded transition-colors",
                showCollapsed ? "justify-center p-2" : "px-2 py-1.5",
                active
                  ? "bg-neutral-100 font-medium text-neutral-900"
                  : "text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900"
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", !showCollapsed && "mr-0")} />
              {!showCollapsed && <span className="ml-2">{label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className={cn("mt-auto flex flex-col gap-1 pt-4", showCollapsed && "items-center")}>
        {BOTTOM_NAV.map(({ href, label, icon: Icon, match }) => {
          const active = match(pathname);
          return (
            <Link
              key={href}
              href={href}
              title={showCollapsed ? label : undefined}
              aria-label={label}
              className={cn(
                "flex items-center rounded text-xs transition-colors",
                showCollapsed ? "justify-center p-2" : "px-2 py-1.5",
                active
                  ? "bg-neutral-100 font-medium text-neutral-900"
                  : "text-neutral-500 hover:bg-neutral-50 hover:text-neutral-800"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!showCollapsed && <span className="ml-2">{label}</span>}
            </Link>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        aria-label={showCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="absolute -right-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-neutral-200 bg-white text-neutral-500 shadow-sm hover:bg-neutral-50 hover:text-neutral-800"
      >
        {showCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
      </button>
    </aside>
  );
}

"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Archive,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  MessageSquare,
  Search,
  Settings,
  Table2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebar } from "@/lib/sidebarContext";
import { WorkspaceSelector } from "@/components/WorkspaceSelector";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, match: (p: string) => p === "/" },
  {
    href: "/vault",
    label: "Vault",
    icon: Archive,
    match: (p: string) => p === "/vault" || p.startsWith("/vault/"),
  },
  {
    href: "/tabular",
    label: "Tabular",
    icon: Table2,
    match: (p: string) => p === "/tabular" || p.startsWith("/tabular/"),
  },
  { href: "/search", label: "Search", icon: Search, match: (p: string) => p === "/search" || p.startsWith("/search/") },
  { href: "/chat", label: "Chat", icon: MessageSquare, match: (p: string) => p === "/chat" || p.startsWith("/chat/") },
  { href: "/settings", label: "Settings", icon: Settings, match: (p: string) => p === "/settings" },
] as const;

export function AppSidebar() {
  const pathname = usePathname();
  const { collapsed, setCollapsed } = useSidebar();

  return (
    <aside
      className={cn(
        "relative flex shrink-0 flex-col border-r border-neutral-200 bg-white p-3 transition-[width] duration-200 motion-reduce:transition-none",
        collapsed ? "w-14" : "w-56"
      )}
    >
      <Link
        href="/"
        className={cn("mb-3 flex items-center gap-2", collapsed && "justify-center")}
        title="Picard.Law OSS"
      >
        <Image src="/picard.svg" alt="Picard.Law OSS" width={28} height={28} className="shrink-0" />
        {!collapsed && (
          <span
            className="min-w-0 font-serif text-sm leading-tight text-neutral-900"
            style={{ fontFamily: "var(--font-garamond), serif" }}
          >
            Picard.Law OSS
          </span>
        )}
      </Link>

      <WorkspaceSelector collapsed={collapsed} />

      <nav className={cn("flex flex-col gap-1 text-sm", collapsed && "items-center")}>
        {NAV.map(({ href, label, icon: Icon, match }) => {
          const active = match(pathname);
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              aria-label={label}
              className={cn(
                "flex items-center rounded transition-colors",
                collapsed ? "justify-center p-2" : "px-2 py-1.5",
                active
                  ? "bg-neutral-100 font-medium text-neutral-900"
                  : "text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900"
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", !collapsed && "mr-0")} />
              {!collapsed && <span className="ml-2">{label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className={cn("mt-auto pt-4", collapsed && "flex justify-center")}>
        <Link
          href="/workspaces"
          title={collapsed ? "Manage workspaces" : undefined}
          aria-label="Manage workspaces"
          className={cn(
            "flex items-center rounded text-xs text-neutral-500 hover:bg-neutral-50 hover:text-neutral-800",
            collapsed ? "p-2" : "block px-2 py-1.5",
            pathname.startsWith("/workspaces") && "font-medium text-neutral-800"
          )}
        >
          <Briefcase className="h-4 w-4 shrink-0" />
          {!collapsed && <span className="ml-2">Manage workspaces</span>}
        </Link>
      </div>

      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="absolute -right-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-neutral-200 bg-white text-neutral-500 shadow-sm hover:bg-neutral-50 hover:text-neutral-800"
      >
        {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
      </button>
    </aside>
  );
}

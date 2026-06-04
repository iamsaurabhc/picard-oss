"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { WorkspaceSelector } from "@/components/WorkspaceSelector";

const NAV = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  { href: "/vault", label: "Vault", match: (p: string) => p === "/vault" || p.startsWith("/vault/") },
  { href: "/tabular", label: "Tabular", match: (p: string) => p === "/tabular" || p.startsWith("/tabular/") },
  { href: "/search", label: "Search", match: (p: string) => p === "/search" || p.startsWith("/search/") },
  { href: "/chat", label: "Chat", match: (p: string) => p === "/chat" || p.startsWith("/chat/") },
  {
    href: "/workflows",
    label: "Workflows",
    match: (p: string) => p === "/workflows" || p.startsWith("/workflows/"),
  },
  { href: "/settings", label: "Settings", match: (p: string) => p === "/settings" },
] as const;

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-neutral-200 bg-white p-4">
      <Link href="/" className="mb-3 flex items-center gap-2">
        <Image src="/picard.svg" alt="Picard.Law OSS" width={28} height={28} className="shrink-0" />
        <span
          className="min-w-0 font-serif text-sm leading-tight text-neutral-900"
          style={{ fontFamily: "var(--font-garamond), serif" }}
        >
          Picard.Law OSS
        </span>
      </Link>
      <WorkspaceSelector />
      <nav className="flex flex-col gap-1 text-sm">
        {NAV.map(({ href, label, match }) => {
          const active = match(pathname);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "rounded px-2 py-1.5 transition-colors",
                active
                  ? "bg-neutral-100 font-medium text-neutral-900"
                  : "text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900"
              )}
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto pt-6">
        <Link
          href="/workspaces"
          className={cn(
            "block rounded px-2 py-1.5 text-xs text-neutral-500 hover:bg-neutral-50 hover:text-neutral-800",
            pathname.startsWith("/workspaces") && "font-medium text-neutral-800"
          )}
        >
          Manage workspaces
        </Link>
      </div>
    </aside>
  );
}

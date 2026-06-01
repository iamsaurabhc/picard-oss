"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/workspaces", label: "Workspaces" },
  { href: "/search", label: "Search" },
  { href: "/chat", label: "Chat" },
] as const;

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-56 flex-col border-r border-neutral-200 bg-white p-4">
      <div className="mb-8 font-serif text-xl" style={{ fontFamily: "var(--font-garamond), serif" }}>
        Picard.Law OSS
      </div>
      <nav className="flex flex-col gap-1 text-sm">
        {NAV.map(({ href, label }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
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
    </aside>
  );
}

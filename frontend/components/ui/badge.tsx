import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const styles: Record<string, string> = {
  pending: "bg-neutral-200 text-neutral-700",
  parsing: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  error: "bg-red-100 text-red-800",
};

export function StatusBadge({ status }: { status: string }) {
  const active = status === "pending" || status === "parsing";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium capitalize",
        styles[status] ?? styles.pending
      )}
    >
      {active ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
      {status}
    </span>
  );
}

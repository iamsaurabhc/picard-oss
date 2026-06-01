import { cn } from "@/lib/utils";

const styles: Record<string, string> = {
  pending: "bg-neutral-200 text-neutral-700",
  parsing: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  error: "bg-red-100 text-red-800",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("rounded px-2 py-0.5 text-xs font-medium capitalize", styles[status] ?? styles.pending)}>
      {status}
    </span>
  );
}

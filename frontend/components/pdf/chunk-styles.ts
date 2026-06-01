import type { ChunkRecord } from "@/lib/picardApi";

export const CHUNK_TYPE_STYLES: Record<
  ChunkRecord["chunk_type"],
  { border: string; bg: string; badge: string }
> = {
  heading: {
    border: "border-blue-500",
    bg: "bg-blue-200/25",
    badge: "bg-blue-100 text-blue-800",
  },
  paragraph: {
    border: "border-neutral-400",
    bg: "bg-neutral-400/15",
    badge: "bg-neutral-100 text-neutral-700",
  },
  table: {
    border: "border-green-500",
    bg: "bg-green-200/25",
    badge: "bg-green-100 text-green-800",
  },
  list: {
    border: "border-amber-500",
    bg: "bg-amber-200/25",
    badge: "bg-amber-100 text-amber-900",
  },
};

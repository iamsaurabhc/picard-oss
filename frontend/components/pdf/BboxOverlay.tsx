import { cn } from "@/lib/utils";
import type { Bbox } from "./bbox-utils";

type Props = {
  bbox: Bbox;
  width: number;
  height: number;
  active?: boolean;
  className?: string;
  label?: string;
};

export function BboxOverlay({ bbox, width, height, active, className, label }: Props) {
  const left = bbox.x0 * width;
  const top = bbox.y0 * height;
  const w = (bbox.x1 - bbox.x0) * width;
  const h = (bbox.y1 - bbox.y0) * height;
  return (
    <div
      className={cn(
        "pointer-events-none absolute border",
        active ? "border-amber-600 bg-amber-400/10" : "border-neutral-400/60 bg-neutral-400/5",
        className
      )}
      style={{ left, top, width: w, height: h }}
    >
      {label && active ? (
        <span className="absolute -top-5 left-0 max-w-full truncate rounded bg-neutral-900 px-1 py-0.5 text-[10px] text-white">
          {label}
        </span>
      ) : null}
    </div>
  );
}

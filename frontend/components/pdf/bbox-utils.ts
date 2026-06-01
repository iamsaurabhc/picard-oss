export type Bbox = { x0: number; y0: number; x1: number; y1: number };

export function isValidBbox(bbox: Record<string, number> | null | undefined): bbox is Bbox {
  if (!bbox || Object.keys(bbox).length === 0) return false;
  const { x0, y0, x1, y1 } = bbox;
  if ([x0, y0, x1, y1].some((v) => typeof v !== "number" || Number.isNaN(v))) return false;
  return x1 > x0 && y1 > y0;
}

export function bboxOverlapRatio(a: Bbox, b: Bbox): number {
  const xOverlap = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0));
  const yOverlap = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  const overlapArea = xOverlap * yOverlap;
  const minArea = Math.min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0));
  if (minArea <= 0) return 0;
  return overlapArea / minArea;
}

export function dedupeByBboxOverlap<T extends { bbox?: Bbox | null }>(
  items: T[],
  threshold = 0.5
): T[] {
  const deduped: T[] = [];
  for (const item of items) {
    const overlapsExisting = deduped.some(
      (existing) =>
        existing.bbox &&
        item.bbox &&
        bboxOverlapRatio(existing.bbox, item.bbox) > threshold
    );
    if (!overlapsExisting) deduped.push(item);
  }
  return deduped;
}

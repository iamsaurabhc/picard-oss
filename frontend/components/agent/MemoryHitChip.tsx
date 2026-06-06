"use client";

type Props = {
  memories: string[];
};

function usefulMemories(memories: string[]): string[] {
  const noise = new Set(["results", "result", "preferences", "preference", "memory", "memories"]);
  return memories.filter((m) => {
    const t = m.trim();
    if (t.length < 16) return false;
    if (noise.has(t.toLowerCase())) return false;
    const words = t.toLowerCase().split(/\s+/);
    if (words.length <= 2 && words.every((w) => noise.has(w))) return false;
    return true;
  });
}

export function MemoryHitChip({ memories }: Props) {
  const shown = usefulMemories(memories);
  if (!shown.length) return null;
  return (
    <div className="mb-2 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
      <p className="font-medium">Recalled from past sessions</p>
      <ul className="mt-1 space-y-1">
        {shown.map((m, i) => (
          <li key={i} className="leading-snug">
            {m}
          </li>
        ))}
      </ul>
    </div>
  );
}

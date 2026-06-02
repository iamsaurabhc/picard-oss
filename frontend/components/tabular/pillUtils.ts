export function getPillClass(content: string): string {
  const lower = content.toLowerCase();
  if (/\b(yes|permitted|allowed)\b/.test(lower)) return "bg-green-100 text-green-800";
  if (/\b(no|not permitted|prohibited)\b/.test(lower)) return "bg-red-100 text-red-800";
  return "bg-neutral-100 text-neutral-700";
}

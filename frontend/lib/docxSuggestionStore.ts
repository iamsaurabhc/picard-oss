import type { DocxSuggestion } from "@/lib/picardApi";

type Listener = (suggestion: DocxSuggestion) => void;

const listeners = new Set<Listener>();
let pending: DocxSuggestion | null = null;

export function subscribeDocxSuggestions(listener: Listener): () => void {
  listeners.add(listener);
  if (pending) listener(pending);
  return () => listeners.delete(listener);
}

export function publishDocxSuggestion(suggestion: DocxSuggestion): void {
  pending = suggestion;
  for (const listener of listeners) listener(suggestion);
}

export function consumeDocxSuggestion(): DocxSuggestion | null {
  const current = pending;
  pending = null;
  return current;
}

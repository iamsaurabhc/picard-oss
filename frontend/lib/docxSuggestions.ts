import type { SuperDocInstance } from "@superdoc-dev/react";
import type { DocxSuggestion } from "@/lib/picardApi";

type DocApi = {
  query?: {
    match?: (input: {
      select: { type: "text"; pattern: string; caseSensitive?: boolean };
      require?: string;
      limit?: number;
    }) => Promise<{
      items?: Array<{ handle?: { ref?: string } }>;
      matches?: Array<{ ref?: string }>;
    }>;
  };
  edit?: {
    replace?: (input: {
      ref: string;
      text: string;
      changeMode?: "tracked" | "direct";
    }) => Promise<unknown>;
  };
};

function activeDocApi(instance: SuperDocInstance | null): DocApi | null {
  const editor = instance?.activeEditor as unknown as { doc?: DocApi } | null | undefined;
  return editor?.doc ?? null;
}

export async function applyDocxSuggestion(
  instance: SuperDocInstance | null,
  suggestion: DocxSuggestion
): Promise<boolean> {
  if (!instance) return false;
  const doc = activeDocApi(instance);
  if (!doc?.query?.match || !doc?.edit?.replace) {
    const matches = instance.search(suggestion.find);
    if (!matches?.[0]) return false;
    instance.goToSearchResult(matches[0]);
    return true;
  }

  let ref: string | undefined;
  try {
    const result = await doc.query.match({
      select: { type: "text", pattern: suggestion.find, caseSensitive: false },
      require: "any",
      limit: 1,
    });
    ref = result.items?.[0]?.handle?.ref ?? result.matches?.[0]?.ref;
  } catch {
    ref = undefined;
  }
  if (!ref) return false;

  await doc.edit.replace({
    ref,
    text: suggestion.replace,
    changeMode: suggestion.change_mode === "tracked" ? "tracked" : "direct",
  });
  return true;
}

import type { SuperDocInstance } from "@superdoc-dev/react";
import type { DocxSuggestion } from "@/lib/picardApi";

type DocApi = {
  query?: {
    match?: (input: {
      select: { type: "text"; pattern: string };
      require?: string;
    }) => Promise<{ matches?: Array<{ ref?: string }> }>;
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

  const result = await doc.query.match({
    select: { type: "text", pattern: suggestion.find },
    require: "first",
  });
  const ref = result.matches?.[0]?.ref;
  if (!ref) return false;

  await doc.edit.replace({
    ref,
    text: suggestion.replace,
    changeMode: suggestion.change_mode === "tracked" ? "tracked" : "direct",
  });
  return true;
}

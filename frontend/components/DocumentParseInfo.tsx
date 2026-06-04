import { cn } from "@/lib/utils";

const sourceStyles: Record<string, string> = {
  digital: "bg-emerald-50 text-emerald-800 border-emerald-200",
  scanned: "bg-amber-50 text-amber-900 border-amber-200",
  mixed: "bg-violet-50 text-violet-900 border-violet-200",
  unknown: "bg-neutral-100 text-neutral-600 border-neutral-200",
};

const sourceLabels: Record<string, string> = {
  digital: "Digital PDF",
  scanned: "Scanned / image",
  mixed: "Mixed layout",
  unknown: "Unknown",
};

const engineLabels: Record<string, string> = {
  none: "No OCR",
  tesseract: "Tesseract",
  paddleocr: "PaddleOCR",
};

export function DocumentParseInfo({
  textSource,
  ocrEngine,
}: {
  textSource: string | null | undefined;
  ocrEngine: string | null | undefined;
}) {
  if (!textSource && !ocrEngine) {
    return <span className="text-xs text-neutral-400">—</span>;
  }

  const source = textSource ?? "unknown";
  const engine = ocrEngine ?? "none";

  return (
    <div className="flex flex-col gap-1">
      <span
        className={cn(
          "inline-flex w-fit rounded border px-2 py-0.5 text-xs font-medium",
          sourceStyles[source] ?? sourceStyles.unknown
        )}
        title={
          source === "digital"
            ? "Native text layer detected; OCR skipped for speed and accuracy."
            : source === "scanned"
              ? "Little or no selectable text; OCR applied during parsing."
              : "Some pages use native text and others need OCR."
        }
      >
        {sourceLabels[source] ?? source}
      </span>
      {engine !== "none" ? (
        <span className="text-xs text-neutral-600">{engineLabels[engine] ?? engine}</span>
      ) : (
        <span className="text-xs text-neutral-500">Native text only</span>
      )}
    </div>
  );
}

export function OcrServerBanner({
  configured,
  reachable,
  serverUrl,
}: {
  configured: boolean;
  reachable: boolean;
  serverUrl: string | null;
}) {
  if (!configured) {
    return (
      <p className="mb-4 rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
        Scanned PDFs use bundled Tesseract OCR
        {reachable ? " (ready)" : " (installing language data on first run…)"}. For higher accuracy, add a PaddleOCR
        server URL in Settings and run <code className="text-neutral-800">./scripts/start-paddleocr.sh</code>.
      </p>
    );
  }
  if (reachable) {
    return (
      <p className="mb-4 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
        PaddleOCR ready at {serverUrl}. Scanned PDFs use OCR at 300 DPI; digital PDFs skip OCR automatically.
      </p>
    );
  }
  return (
    <p className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
      PaddleOCR configured ({serverUrl}) but not reachable. Scanned PDFs will fall back to Tesseract until the server is
      running.
    </p>
  );
}

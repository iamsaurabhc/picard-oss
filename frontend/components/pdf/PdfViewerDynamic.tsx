"use client";

import dynamic from "next/dynamic";

function PdfLoading() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-neutral-500">
      Loading PDF…
    </div>
  );
}

export const MultiHighlightPDFViewer = dynamic(
  () =>
    import("@/components/MultiHighlightPDFViewer").then((m) => m.MultiHighlightPDFViewer),
  { ssr: false, loading: PdfLoading }
);

export const LayoutPDFViewer = dynamic(
  () => import("@/components/LayoutPDFViewer").then((m) => m.LayoutPDFViewer),
  { ssr: false, loading: PdfLoading }
);

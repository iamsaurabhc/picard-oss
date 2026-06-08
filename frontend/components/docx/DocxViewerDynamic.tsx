"use client";

import dynamic from "next/dynamic";
import type { ComponentProps } from "react";
import type { DocxPageViewer } from "./DocxPageViewer";

const DocxPageViewerDynamic = dynamic(
  () => import("./DocxPageViewer").then((m) => m.DocxPageViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-sm text-neutral-500">
        Loading editor…
      </div>
    ),
  }
);

export type DocxViewerProps = ComponentProps<typeof DocxPageViewer>;

export function DocxViewerDynamic(props: DocxViewerProps) {
  return <DocxPageViewerDynamic {...props} />;
}

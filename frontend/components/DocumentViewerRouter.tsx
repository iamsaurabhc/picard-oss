"use client";

import type { ComponentProps } from "react";
import { LayoutPDFViewer } from "@/components/pdf/PdfViewerDynamic";
import { DocxViewerDynamic } from "@/components/docx/DocxViewerDynamic";
import type { DocumentRecord } from "@/lib/picardApi";

type PdfProps = ComponentProps<typeof LayoutPDFViewer>;
type DocxProps = ComponentProps<typeof DocxViewerDynamic>;

type Props =
  | ({ document: DocumentRecord } & { variant: "pdf" } & PdfProps)
  | ({ document: DocumentRecord } & { variant: "docx" } & DocxProps);

export function DocumentViewerRouter(props: Props) {
  const fileType = props.document.file_type ?? "pdf";
  if (fileType === "docx") {
    const { document: _doc, variant: _v, ...docxProps } = props as Extract<Props, { variant: "docx" }>;
    return <DocxViewerDynamic {...docxProps} />;
  }
  const { document: _doc, variant: _v, ...pdfProps } = props as Extract<Props, { variant: "pdf" }>;
  return <LayoutPDFViewer {...pdfProps} />;
}

export function isDocxDocument(document: DocumentRecord): boolean {
  return (document.file_type ?? "pdf") === "docx";
}

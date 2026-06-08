export const ACCEPTED_DOCUMENT_EXTENSIONS = [".pdf", ".docx"] as const;

export const DOCUMENT_UPLOAD_ACCEPT =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function isAcceptedDocumentFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  return lower.endsWith(".pdf") || lower.endsWith(".docx");
}

export function documentTypeLabel(fileType: string | undefined): string {
  if (fileType === "docx") return "Word";
  return "PDF";
}

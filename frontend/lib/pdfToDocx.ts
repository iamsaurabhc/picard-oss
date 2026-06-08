import {
  WorkerBrowserConverter,
  createWasmPaths,
  type ConversionResult,
} from "@matbee/libreoffice-converter/browser";

const WASM_BASE = "/libreoffice-wasm/";

let converter: WorkerBrowserConverter | null = null;
let initPromise: Promise<WorkerBrowserConverter> | null = null;

export type PdfToDocxProgress = {
  percent: number;
  message: string;
};

async function getConverter(
  onProgress?: (progress: PdfToDocxProgress) => void
): Promise<WorkerBrowserConverter> {
  if (converter?.isReady()) return converter;
  if (initPromise) return initPromise;

  initPromise = (async () => {
    const wasmPaths = createWasmPaths(WASM_BASE);
    const instance = new WorkerBrowserConverter({
      ...wasmPaths,
      browserWorkerJs: `${WASM_BASE}browser.worker.global.js`,
      onProgress: (info) => {
        onProgress?.({ percent: info.percent, message: info.message });
      },
    });
    await instance.initialize();
    converter = instance;
    return instance;
  })();

  return initPromise;
}

export async function convertPdfToDocx(
  pdfBytes: ArrayBuffer,
  fileName: string,
  onProgress?: (progress: PdfToDocxProgress) => void
): Promise<ConversionResult> {
  const conv = await getConverter(onProgress);
  return conv.convert(new Uint8Array(pdfBytes), { outputFormat: "docx", inputFormat: "pdf" }, fileName);
}

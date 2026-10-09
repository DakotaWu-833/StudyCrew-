import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { Button, Loading } from "../components/UI";
import { errorMessage } from "../api/client";

export default function PdfFilePreview({ blob, onRendered }: { blob: Blob; onRendered?: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    let loading: ReturnType<typeof import("pdfjs-dist").getDocument> | undefined;
    setPdf(null); setPage(1); setBusy(true); setError("");
    void (async () => {
      const renderer = await import("pdfjs-dist");
      if (disposed) return;
      renderer.GlobalWorkerOptions.workerSrc = workerUrl;
      const data = new Uint8Array(await blob.arrayBuffer());
      if (disposed) return;
      // PDF.js 6 removed the eval option and eval path. Render from verified
      // bytes only; no document URL, scripting manager, XFA or remote assets.
      loading = renderer.getDocument({ data, useWorkerFetch: false, useWasm: false, enableXfa: false,
        disableFontFace: true, useSystemFonts: true, stopAtErrors: true, maxImageSize: 20_000_000,
        canvasMaxAreaInBytes: 32 * 1024 * 1024 });
      const document = await loading.promise;
      if (!disposed) setPdf(document);
    })().catch(failure => { if (!disposed) { setError(errorMessage(failure)); setBusy(false); } });
    return () => { disposed = true; void loading?.destroy().catch(() => undefined); };
  }, [blob]);
  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let disposed = false;
    let rendering: RenderTask | undefined;
    setBusy(true); setError("");
    void (async () => {
      const selected = await pdf.getPage(page);
      if (disposed || !canvas.current) return;
      const original = selected.getViewport({ scale: 1 });
      const scale = Math.min(1.6, 1600 / original.width, 4096 / original.height,
        Math.sqrt(4_000_000 / (original.width * original.height)));
      const viewport = selected.getViewport({ scale });
      const target = canvas.current;
      target.width = Math.ceil(viewport.width); target.height = Math.ceil(viewport.height);
      // Canvas-only rendering has no link, annotation, form or scripting layer.
      rendering = selected.render({ canvas: target, viewport, annotationMode: 0 });
      await rendering.promise;
      if (!disposed) { setBusy(false); onRendered?.(); }
    })().catch(failure => { if (!disposed) { setError(errorMessage(failure)); setBusy(false); } });
    return () => { disposed = true; rendering?.cancel(); };
  }, [pdf, page, onRendered]);
  return <div className="private-file-pdf">
    {error && <p className="notice notice--error" role="alert">PDF preview could not be displayed: {error}. You can still download the file.</p>}
    {busy && <Loading label="Rendering PDF page…" />}
    {pdf && <div className="row-actions"><Button type="button" variant="quiet" disabled={page <= 1 || busy} onClick={() => setPage(page - 1)}>Previous PDF page</Button><span>Page {page} of {pdf.numPages}</span><Button type="button" variant="quiet" disabled={page >= pdf.numPages || busy} onClick={() => setPage(page + 1)}>Next PDF page</Button></div>}
    <canvas ref={canvas} role="img" aria-label={`PDF page ${page}`} hidden={Boolean(error)} />
    <p className="muted">Visual preview only. Download the original for selectable text and accessible document features.</p>
  </div>;
}

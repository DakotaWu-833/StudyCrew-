import { useCallback, useEffect, useRef, useState } from "react";
import { privateFilesApi, type FileVersion } from "../api/privateFiles";
import { errorMessage } from "../api/client";
import { Button, Loading, Panel } from "../components/UI";
import PdfFilePreview from "./PdfFilePreview";

export default function FilePreview({ projectId, documentId, version, onClose }: {
  projectId: string; documentId: string; version: FileVersion; onClose: () => void;
}) {
  const [preview, setPreview] = useState<{ text?: string; url?: string; blob?: Blob; truncated: boolean } | null>(null);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const reveal = useCallback(() => {
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }, []);
  useEffect(reveal, [reveal, version.id, preview]);
  useEffect(() => {
    let disposed = false;
    let objectUrl = "";
    setPreview(null); setError("");
    void privateFilesApi.preview(projectId, documentId, version.id).then(async result => {
      if (disposed) return;
      if (version.preview_kind === "text") {
        const text = await result.blob.text();
        if (!disposed) setPreview({ text, truncated: result.truncated });
      } else if (version.preview_kind === "image") {
        objectUrl = URL.createObjectURL(result.blob);
        setPreview({ url: objectUrl, truncated: false });
      } else if (version.preview_kind === "pdf") setPreview({ blob: result.blob, truncated: false });
    }).catch(failure => { if (!disposed) setError(errorMessage(failure)); });
    return () => { disposed = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [projectId, documentId, version.id, version.preview_kind]);
  return <Panel><div className="section-heading"><h3 ref={heading} tabIndex={-1}>Preview · Version {version.number}: {version.filename}</h3><Button type="button" variant="quiet" onClick={onClose}>Close preview</Button></div>
    {error && <p role="alert" className="notice notice--error">{error}</p>}
    {!error && !preview && <Loading label="Loading private file preview…" />}
    {preview?.text !== undefined && <pre className="private-file-text">{preview.text}</pre>}
    {preview?.truncated && <p className="notice">Showing the first 512 KB. Download the file to read the rest.</p>}
    {preview?.url && <img className="private-file-image" src={preview.url} alt={`Preview of ${version.filename}`} onLoad={reveal} />}
    {preview?.blob && <PdfFilePreview blob={preview.blob} onRendered={reveal} />}
    <a href={version.download_url}>Download original</a>
  </Panel>;
}

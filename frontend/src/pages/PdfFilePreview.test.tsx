import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import PdfFilePreview from "./PdfFilePreview";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";

vi.mock("pdfjs-dist", () => ({ getDocument: vi.fn(), GlobalWorkerOptions: { workerSrc: "" } }));
let root: Root, container: HTMLDivElement;
let destroy: ReturnType<typeof vi.fn>, cancel: ReturnType<typeof vi.fn>, renderPage: ReturnType<typeof vi.fn>, getPage: ReturnType<typeof vi.fn>;
const blob = { arrayBuffer: async () => new Uint8Array([37, 80, 68, 70]).buffer } as Blob;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  destroy = vi.fn().mockResolvedValue(undefined); cancel = vi.fn();
  renderPage = vi.fn().mockReturnValue({ promise: Promise.resolve(), cancel });
  getPage = vi.fn().mockResolvedValue({ getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }), render: renderPage });
  vi.mocked(getDocument).mockReturnValue({ promise: Promise.resolve({ numPages: 2, getPage }), destroy } as never);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render() { await act(async () => { root.render(<PdfFilePreview blob={blob} />); await new Promise(resolve => setTimeout(resolve, 25)); }); await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }

it("renders verified PDF bytes to bounded canvas without script, XFA, form or link layers", async () => {
  await render();
  expect(getDocument).toHaveBeenCalledWith(expect.objectContaining({ data: expect.any(Uint8Array), useWorkerFetch: false, useWasm: false, enableXfa: false, disableFontFace: true, maxImageSize: 20_000_000 }));
  expect(GlobalWorkerOptions.workerSrc).toContain("pdf.worker.min.mjs");
  expect(renderPage).toHaveBeenCalledWith(expect.objectContaining({ canvas: expect.any(HTMLCanvasElement), annotationMode: 0 }));
  expect(container.querySelector("iframe,object,script,a,input")).toBeNull();
  expect(container.textContent).toContain("Page 1 of 2");
  expect(container.querySelector("canvas")!.width).toBeLessThanOrEqual(1600);
});

it("changes one page at a time and destroys the parsing worker on dismissal", async () => {
  await render();
  await act(async () => { [...container.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === "Next PDF page")!.click(); await new Promise(resolve => setTimeout(resolve, 25)); });
  expect(getPage).toHaveBeenLastCalledWith(2);
  expect(container.textContent).toContain("Page 2 of 2");
  expect([...container.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === "Next PDF page")!.disabled).toBe(true);
  await act(async () => root.render(null));
  expect(destroy).toHaveBeenCalledOnce();
});

it("caps unusually large page dimensions and provides a download fallback on parser errors", async () => {
  getPage.mockResolvedValue({ getViewport: ({ scale }: { scale: number }) => ({ width: 100_000 * scale, height: 100_000 * scale }), render: renderPage });
  await render();
  const canvas = container.querySelector("canvas")!;
  expect(canvas.width * canvas.height).toBeLessThanOrEqual(4_000_000);
  vi.mocked(getDocument).mockImplementation(() => ({ promise: Promise.reject(new Error("Invalid PDF structure")), destroy } as never));
  const invalid = { arrayBuffer: async () => new Uint8Array([1]).buffer } as Blob;
  await act(async () => { root.render(<PdfFilePreview blob={invalid} />); await new Promise(resolve => setTimeout(resolve, 25)); });
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("You can still download the file");
  expect(container.querySelector("canvas")!.hidden).toBe(true);
});

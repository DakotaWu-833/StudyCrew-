from __future__ import annotations

import argparse
from pathlib import Path

import pythoncom
import pypdfium2 as pdfium
import win32com.client


def export_docx(docx_path: Path, pdf_path: Path) -> None:
    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(docx_path.resolve()), ReadOnly=True, AddToRecentFiles=False)
        document.ExportAsFixedFormat(str(pdf_path.resolve()), 17, OpenAfterExport=False)
    finally:
        if document is not None:
            document.Close(False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()


def render_pdf(pdf_path: Path, output_dir: Path, scale: float = 1.6) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    for index in range(len(pdf)):
        page = pdf[index]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        image.save(output_dir / f"page-{index + 1:03d}.png")
        page.close()
    return len(pdf)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("render_dir", type=Path)
    args = parser.parse_args()
    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    export_docx(args.docx, args.pdf)
    count = render_pdf(args.pdf, args.render_dir)
    print(f"Exported {args.pdf} and rendered {count} pages to {args.render_dir}")


if __name__ == "__main__":
    main()


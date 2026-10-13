"""Isolated PDF/DOCX parser. Stdout contains bounded text, never diagnostics."""
import io
import json
import sys
import zipfile
from xml.etree import ElementTree

MAX_CHARS = 32000
MAX_PAGES = 30


def parse(payload, extension):
    pages = []
    limited = False
    if extension == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted document")
        limited = len(reader.pages) > MAX_PAGES
        remaining = MAX_CHARS
        for index, page in enumerate(reader.pages[:MAX_PAGES], 1):
            text = page.extract_text() or ""
            pages.append({"page": index, "text": text[:remaining]})
            remaining -= len(text)
            if remaining <= 0:
                limited = True
                break
    elif extension == "docx":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if len(archive.infolist()) > 500 or sum(row.file_size for row in archive.infolist()) > 16 * 1024 * 1024:
                raise ValueError("Expanded document too large")
            entry = archive.getinfo("word/document.xml")
            if entry.file_size > 1024 * 1024:
                raise ValueError("Document XML too large")
            xml = archive.read(entry)
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise ValueError("Unsupported XML")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            text = "\n".join("".join(node.itertext()) for node in root.iter(ns + "p"))
            limited = len(text) > MAX_CHARS
            pages = [{"page": None, "text": text[:MAX_CHARS]}]
    else:
        raise ValueError("Unsupported document")
    return {"pages": pages, "limited": limited}


if __name__ == "__main__":
    # Limit the parser on Unix; the parent also enforces a wall-clock timeout.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    except ImportError:
        pass
    try:
        data = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("Document too large")
        print(json.dumps(parse(data, sys.argv[1]), ensure_ascii=True))
    except Exception:
        sys.exit(2)

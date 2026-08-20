from __future__ import annotations

import argparse
from pathlib import Path

import pythoncom
import win32com.client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx", type=Path)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    args.pdf.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    powerpoint = None
    presentation = None
    try:
        powerpoint = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = powerpoint.Presentations.Open(
            str(args.pptx.resolve()), WithWindow=False, ReadOnly=True
        )
        presentation.SaveAs(str(args.pdf.resolve()), 32)
    finally:
        if presentation is not None:
            presentation.Close()
        if powerpoint is not None:
            powerpoint.Quit()
        pythoncom.CoUninitialize()

    print(f"Exported {args.pdf}")


if __name__ == "__main__":
    main()

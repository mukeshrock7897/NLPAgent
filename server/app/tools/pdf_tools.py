from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv()

def _extract_with_pypdf(path: Path) -> str:
    reader = PdfReader(str(path))
    texts = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except Exception:
                pass
        if text.strip():
            texts.append(f"[Page {i}]\n{text.strip()}")
    return "\n\n".join(texts).strip()


def _extract_with_pdfplumber(path: Path) -> str:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return ""
    texts = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                texts.append(f"[Page {i}]\n{text.strip()}")
    return "\n\n".join(texts).strip()


def _extract_with_pymupdf(path: Path) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    texts = []
    doc = fitz.open(str(path))
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        if text.strip():
            texts.append(f"[Page {i}]\n{text.strip()}")
    return "\n\n".join(texts).strip()


def read_pdf_local(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {p}")

    candidates = [
        _extract_with_pypdf(p),
        _extract_with_pdfplumber(p),
        _extract_with_pymupdf(p),
    ]
    best = max(candidates, key=lambda t: len(t or ""))
    if not best or len(best.strip()) < 40:
        raise ValueError("No extractable text found in PDF. Try an OCR-based PDF.")
    return best

def read_pdf_from_s3(s3_uri: str) -> str:
    if not s3_uri.startswith("s3://"):
        raise ValueError("s3_uri must start with s3://")
    _, _, rest = s3_uri.partition("s3://")
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError("Invalid S3 URI. Expected s3://bucket/key")

    import boto3  # type: ignore
    region = os.getenv("AWS_REGION") or None
    s3 = boto3.client("s3", region_name=region)

    with tempfile.TemporaryDirectory() as td:
        local_path = Path(td) / Path(key).name
        s3.download_file(bucket, key, str(local_path))
        return read_pdf_local(str(local_path))

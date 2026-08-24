from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.core.config import BACKEND_ROOT


TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")


def _tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("_", " ")
    return {token.lower() for token in TOKEN_RE.findall(normalized)}


def _resolve_document_path(document_path: str) -> Path:
    path = Path(document_path)
    if path.is_absolute():
        return path
    return Path(BACKEND_ROOT) / path


def _chunk_text(text: str, max_chars: int = 1400) -> list[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []

    paragraphs = re.split(r"\n{2,}", cleaned)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue
        if len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _read_text_file(path: Path) -> list[dict[str, Any]]:
    return [{"page": 1, "text": path.read_text(encoding="utf-8", errors="ignore")}]


def _read_docx_file(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        xml_data = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_data)
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespaces):
        runs = [node.text for node in paragraph.findall(".//w:t", namespaces) if node.text]
        if runs:
            paragraphs.append("".join(runs))
    return [{"page": 1, "text": "\n\n".join(paragraphs)}]


def _read_pdf_file(path: Path) -> list[dict[str, Any]]:
    import pymupdf  # type: ignore

    result: list[dict[str, Any]] = []
    with pymupdf.open(path) as document:
        for index, page in enumerate(document, start=1):
            result.append({"page": index, "text": page.get_text("text")})
    return result


@lru_cache
def load_document_chunks(document_path: str) -> tuple[dict[str, Any], ...]:
    path = _resolve_document_path(document_path)
    if not path.exists():
        return tuple()

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        pages = _read_text_file(path)
    elif suffix == ".docx":
        pages = _read_docx_file(path)
    elif suffix == ".pdf":
        pages = _read_pdf_file(path)
    else:
        return tuple()

    chunks: list[dict[str, Any]] = []
    for page_data in pages:
        for chunk in _chunk_text(page_data["text"]):
            chunks.append({"page": page_data["page"], "text": chunk})
    return tuple(chunks)


def retrieve_document_context(documents: list[dict[str, Any]], query: str, top_k: int = 3) -> list[dict[str, Any]]:
    query_tokens = _tokenize(query)
    scored: list[dict[str, Any]] = []

    for document in documents:
        path = document.get("path")
        if not path:
            continue
        document_tokens = _tokenize(
            " ".join(
                value
                for value in [
                    document.get("document_id") or "",
                    document.get("filename") or "",
                    document.get("title") or "",
                    str(path),
                ]
                if value
            )
        )
        for chunk in load_document_chunks(path):
            chunk_tokens = _tokenize(chunk["text"])
            overlap = query_tokens & chunk_tokens
            score = len(overlap)
            title_overlap = query_tokens & document_tokens
            score += len(title_overlap)
            if score <= 0:
                continue
            scored.append(
                {
                    "document_id": document.get("document_id"),
                    "filename": document.get("filename"),
                    "path": path,
                    "title": document.get("title"),
                    "page": chunk["page"],
                    "score": score,
                    "text": chunk["text"],
                }
            )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def serialize_context_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": chunk["document_id"],
            "filename": chunk["filename"],
            "path": chunk["path"],
            "title": chunk["title"],
            "page": chunk["page"],
            "score": chunk["score"],
            "excerpt": chunk["text"][:800],
        }
        for chunk in chunks
    ]


def context_to_prompt(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(
            json.dumps(
                {
                    "document_id": chunk["document_id"],
                    "filename": chunk["filename"],
                    "title": chunk["title"],
                    "page": chunk["page"],
                    "text": chunk["text"],
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(parts)

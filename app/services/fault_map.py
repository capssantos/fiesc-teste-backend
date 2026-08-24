from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings


@lru_cache
def _load_map(map_path: str) -> dict[str, Any]:
    path = Path(map_path)
    if not path.exists():
        return {"faults": {}, "normalization": {"typo_aliases": {}}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"faults": {}, "normalization": {"typo_aliases": {}}}


def load_fault_map() -> dict[str, Any]:
    return _load_map(settings.fault_document_map_path)


def get_fault_entry(raw_fault: str) -> dict[str, Any] | None:
    mapping = load_fault_map()
    faults = mapping.get("faults", {})
    typo_aliases = mapping.get("normalization", {}).get("typo_aliases", {})
    normalized = typo_aliases.get(raw_fault, raw_fault)

    for canonical_key, entry in faults.items():
        raw_labels = entry.get("raw_labels", [])
        if normalized == canonical_key or normalized == entry.get("canonical_label") or normalized in raw_labels:
            return {
                "canonical_key": canonical_key,
                "canonical_label": entry.get("canonical_label", canonical_key),
                "kind": entry.get("kind", "fault"),
                "recommendation_supported": entry.get("recommendation_supported", False),
                "documents": entry.get("documents", []),
                "candidate_documents": entry.get("candidate_documents", []),
                "raw_labels": raw_labels,
                "notes": entry.get("notes", []),
                "metadata": {"resolved_label": normalized},
            }
    return None


def get_documents_for_entry(entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not entry:
        return []

    mapping = load_fault_map()
    document_map = mapping.get("documents", {})
    documents: list[dict[str, Any]] = []
    for document_id in entry.get("documents", []):
        document_data = document_map.get(document_id, {})
        documents.append(
            {
                "document_id": document_id,
                "filename": Path(document_data.get("path", "")).name or None,
                "path": document_data.get("path"),
                "title": document_data.get("title"),
            }
        )
    return documents


def list_fault_entries() -> list[dict[str, Any]]:
    mapping = load_fault_map()
    items: list[dict[str, Any]] = []
    for canonical_key, entry in mapping.get("faults", {}).items():
        items.append(
            {
                "canonical_key": canonical_key,
                "canonical_label": entry.get("canonical_label", canonical_key),
                "kind": entry.get("kind", "fault"),
                "recommendation_supported": entry.get("recommendation_supported", False),
                "documents": entry.get("documents", []),
                "candidate_documents": entry.get("candidate_documents", []),
            }
        )
    return items

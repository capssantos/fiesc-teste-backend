from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.document_retrieval import context_to_prompt, retrieve_document_context, serialize_context_chunks
from app.services.fault_map import get_documents_for_entry, get_fault_entry
from app.services.llm_client import LLMProviderError, generate_llm_text
from app.services.rag_index import retrieve_indexed_document_context


SYSTEM_PROMPT = """Voce e um assistente de manutencao industrial.
Responda exclusivamente com base no CONTEXTO TECNICO fornecido.
Nao use conhecimento externo.
Se o contexto nao for suficiente, diga explicitamente que a documentacao disponivel e insuficiente.
Retorne JSON com as chaves: summary, recommended_actions, inspection_points, warnings.
"""


def build_recommendation_for_fault(fault_label: str, user_message: str, db: Session | None = None) -> dict[str, Any]:
    entry = get_fault_entry(fault_label)
    if entry is None or not entry["recommendation_supported"]:
        return {
            "status": "documentation_not_found",
            "recommendation_available": False,
            "message": "Nao ha documentacao tecnica suportada para a falha identificada.",
            "sources": [],
            "context_chunks": [],
        }

    documents = get_documents_for_entry(entry)
    query = f"{fault_label} {entry['canonical_label']} {user_message} diagnostico correcao manutencao inspecao"
    chunks = retrieve_indexed_document_context(db, documents, query, top_k=3) if db else []
    if not chunks:
        chunks = retrieve_document_context(documents, query, top_k=3)
    serialized_chunks = serialize_context_chunks(chunks)

    if not serialized_chunks:
        return {
            "status": "insufficient_document_context",
            "recommendation_available": False,
            "message": "A documentacao mapeada existe, mas o contexto recuperado foi insuficiente.",
            "sources": documents,
            "context_chunks": [],
        }

    if not settings.llm_configured:
        return {
            "status": "llm_not_configured",
            "recommendation_available": False,
            "message": "Documentacao suportada encontrada, mas o LLM nao esta configurado.",
            "sources": documents,
            "context_chunks": serialized_chunks,
        }

    prompt = (
        f"Falha em analise: {entry['canonical_label']}\n"
        f"Pergunta do usuario: {user_message}\n"
        f"CONTEXTO TECNICO:\n{context_to_prompt(chunks)}"
    )
    try:
        raw_response = generate_llm_text(SYSTEM_PROMPT, prompt)
    except LLMProviderError as exc:
        return {
            "status": exc.code,
            "recommendation_available": False,
            "message": exc.message,
            "sources": documents,
            "context_chunks": serialized_chunks,
        }

    try:
        parsed = json.loads(raw_response)
    except Exception:
        parsed = {
            "summary": raw_response,
            "recommended_actions": [],
            "inspection_points": [],
            "warnings": [],
        }

    return {
        "status": "completed",
        "recommendation_available": True,
        "fault": entry["canonical_label"],
        "summary": parsed.get("summary"),
        "recommended_actions": parsed.get("recommended_actions", []),
        "inspection_points": parsed.get("inspection_points", []),
        "warnings": parsed.get("warnings", []),
        "sources": documents,
        "context_chunks": serialized_chunks,
        "raw_response": raw_response,
    }

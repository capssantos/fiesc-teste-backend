from __future__ import annotations

import csv
import heapq
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.document_retrieval import retrieve_document_context, serialize_context_chunks
from app.services.fault_map import get_documents_for_entry, get_fault_entry
from app.services.recommendation import build_recommendation_for_fault
from app.services.rag_index import retrieve_indexed_document_context


FEATURE_COLUMNS = [
    "temperature_c",
    "z_rms_velocity_in_s",
    "x_rms_velocity_in_s",
    "z_peak_acceleration_g",
    "x_peak_acceleration_g",
    "z_peak_vel_comp_freq_hz",
    "x_peak_vel_comp_freq_hz",
    "z_rms_acceleration_g",
    "x_rms_acceleration_g",
    "z_kurtosis",
    "x_kurtosis",
    "z_crest_factor",
    "x_crest_factor",
    "z_peak_velocity_in_s",
    "x_peak_velocity_in_s",
    "z_high_freq_rms_accel_g",
    "x_high_freq_rms_accel_g",
    "rpm",
]


@dataclass(frozen=True)
class DatasetRow:
    source_id: str
    created_at: datetime
    raw_fault: str
    canonical_label: str
    kind: str
    recommendation_supported: bool
    documents: tuple[dict[str, Any], ...]
    features: tuple[float, ...]
    metrics: dict[str, float]


@dataclass(frozen=True)
class DatasetBundle:
    rows: tuple[DatasetRow, ...]
    feature_columns: tuple[str, ...]
    means: tuple[float, ...]
    stds: tuple[float, ...]
    medians: tuple[float, ...]
    scaled_rows: tuple[tuple[float, ...], ...]
    scaled_norms: tuple[float, ...]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _parse_created_at(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _extract_feature(mapping: dict[str, Any], feature_name: str) -> float | None:
    direct = _to_float(mapping.get(feature_name))
    if direct is not None:
        return direct

    if feature_name == "temperature_c":
        temperature_f = _to_float(mapping.get("temperature_f"))
        return None if temperature_f is None else (temperature_f - 32.0) * 5.0 / 9.0

    conversions = {
        "z_rms_velocity_in_s": "z_rms_velocity_mm_s",
        "x_rms_velocity_in_s": "x_rms_velocity_mm_s",
        "z_peak_velocity_in_s": "z_peak_velocity_mm_s",
        "x_peak_velocity_in_s": "x_peak_velocity_mm_s",
    }
    mm_field = conversions.get(feature_name)
    if mm_field:
        mm_value = _to_float(mapping.get(mm_field))
        return None if mm_value is None else mm_value / 25.4

    return None


def _median(sorted_values: list[float]) -> float:
    size = len(sorted_values)
    if size == 0:
        return 0.0
    middle = size // 2
    if size % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


@lru_cache
def load_dataset() -> DatasetBundle:
    dataset_path = Path(settings.dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    rows: list[DatasetRow] = []
    feature_values: dict[str, list[float]] = {column: [] for column in FEATURE_COLUMNS}

    with dataset_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            feature_vector: list[float] = []
            metrics: dict[str, float] = {}
            for feature in FEATURE_COLUMNS:
                value = _extract_feature(row, feature)
                if value is None:
                    value = 0.0
                feature_vector.append(value)
                feature_values[feature].append(value)
                metrics[feature] = value

            raw_fault = (row.get("fault") or "").strip()
            fault_entry = get_fault_entry(raw_fault)
            canonical_label = fault_entry["canonical_label"] if fault_entry else raw_fault
            kind = fault_entry["kind"] if fault_entry else "fault"
            recommendation_supported = bool(fault_entry and fault_entry["recommendation_supported"])
            documents = tuple(get_documents_for_entry(fault_entry) if fault_entry else [])

            rows.append(
                DatasetRow(
                    source_id=str(row.get("id", "")),
                    created_at=_parse_created_at(row["created_at"]),
                    raw_fault=raw_fault,
                    canonical_label=canonical_label,
                    kind=kind,
                    recommendation_supported=recommendation_supported,
                    documents=documents,
                    features=tuple(feature_vector),
                    metrics=metrics,
                )
            )

    means: list[float] = []
    stds: list[float] = []
    medians: list[float] = []
    for feature in FEATURE_COLUMNS:
        values = feature_values[feature]
        count = len(values)
        mean = sum(values) / count
        variance = sum((value - mean) ** 2 for value in values) / count
        std = math.sqrt(variance) or 1.0
        means.append(mean)
        stds.append(std)
        medians.append(_median(sorted(values)))

    scaled_rows: list[tuple[float, ...]] = []
    scaled_norms: list[float] = []
    for row in rows:
        scaled = tuple((value - means[idx]) / stds[idx] for idx, value in enumerate(row.features))
        scaled_rows.append(scaled)
        scaled_norms.append(math.sqrt(sum(component * component for component in scaled)) or 1.0)

    return DatasetBundle(
        rows=tuple(rows),
        feature_columns=tuple(FEATURE_COLUMNS),
        means=tuple(means),
        stds=tuple(stds),
        medians=tuple(medians),
        scaled_rows=tuple(scaled_rows),
        scaled_norms=tuple(scaled_norms),
    )


def _build_query_features(event_payload: dict[str, Any], dataset: DatasetBundle) -> tuple[float, ...]:
    values: list[float] = []
    for index, feature in enumerate(dataset.feature_columns):
        value = _extract_feature(event_payload, feature)
        if value is None:
            value = dataset.medians[index]
        values.append(value)
    return tuple(values)


def _scale_query(raw_values: tuple[float, ...], dataset: DatasetBundle) -> tuple[float, ...]:
    return tuple((value - dataset.means[idx]) / dataset.stds[idx] for idx, value in enumerate(raw_values))


def _distance(query_scaled: tuple[float, ...], row_scaled: tuple[float, ...]) -> float:
    if settings.similarity_metric == "cosine":
        dot = sum(left * right for left, right in zip(query_scaled, row_scaled))
        query_norm = math.sqrt(sum(value * value for value in query_scaled)) or 1.0
        row_norm = math.sqrt(sum(value * value for value in row_scaled)) or 1.0
        return 1.0 - (dot / (query_norm * row_norm))
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(query_scaled, row_scaled)))


def _similarity_score(distance: float) -> float:
    return 1.0 / (1.0 + max(distance, 0.0))


def _neighbor_payload(row: DatasetRow, distance: float) -> dict[str, Any]:
    return {
        "id": row.source_id,
        "created_at": row.created_at.isoformat(),
        "fault": row.raw_fault,
        "canonical_fault": row.canonical_label,
        "kind": row.kind,
        "distance": round(distance, 6),
        "similarity_score": round(_similarity_score(distance), 6),
        "metrics": {
            "temperature_c": row.metrics.get("temperature_c"),
            "rpm": row.metrics.get("rpm"),
            "z_rms_velocity_in_s": row.metrics.get("z_rms_velocity_in_s"),
            "x_rms_velocity_in_s": row.metrics.get("x_rms_velocity_in_s"),
        },
    }


def _aggregate_neighbors(neighbors: list[dict[str, Any]]) -> tuple[str | None, str | None, dict[str, Any]]:
    weighted_votes: dict[str, float] = {}
    counts: Counter[str] = Counter()
    kinds: dict[str, str] = {}

    for neighbor in neighbors:
        label = neighbor["canonical_fault"] or neighbor["fault"]
        kinds[label] = neighbor.get("kind") or "fault"
        counts[label] += 1
        weighted_votes[label] = weighted_votes.get(label, 0.0) + float(neighbor["similarity_score"])

    if not weighted_votes:
        return None, None, {"vote_strategy": "distance_weighted_vote", "neighbors": 0}

    winner = max(weighted_votes.items(), key=lambda item: (item[1], counts[item[0]]))[0]
    evidence = {
        "vote_strategy": "distance_weighted_vote",
        "neighbors": len(neighbors),
        "label_counts": dict(counts),
        "weighted_votes": {key: round(value, 6) for key, value in weighted_votes.items()},
        "historical_similarity_evidence": f"{counts[winner]} of {len(neighbors)} neighbors matched {winner}.",
        "predominant_label": winner,
    }
    if kinds.get(winner) == "non_fault":
        return None, "operational_state", evidence
    return winner, "fault", evidence


def _describe_history(rows: list[DatasetRow], target_label: str, neighbors: list[dict[str, Any]]) -> dict[str, Any]:
    matching = [row for row in rows if row.canonical_label == target_label]
    if not matching:
        return {}

    first_seen = min(row.created_at for row in matching)
    last_seen = max(row.created_at for row in matching)
    span_days = max((last_seen.date() - first_seen.date()).days, 0)
    granularity = "day" if span_days <= 62 else "month"
    distribution_counter: Counter[str] = Counter()
    for row in matching:
        key = row.created_at.date().isoformat() if granularity == "day" else row.created_at.strftime("%Y-%m")
        distribution_counter[key] += 1

    def _metric_stats(metric_name: str) -> dict[str, float] | None:
        values = [row.metrics[metric_name] for row in matching if metric_name in row.metrics]
        if not values:
            return None
        return {
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "mean": round(sum(values) / len(values), 6),
        }

    return {
        "total_occurrences": len(matching),
        "neighbor_occurrences": sum(1 for neighbor in neighbors if neighbor["canonical_fault"] == target_label),
        "first_occurrence": first_seen.isoformat(),
        "last_occurrence": last_seen.isoformat(),
        "distribution_granularity": granularity,
        "distribution": dict(sorted(distribution_counter.items())),
        "operating_conditions": {
            "rpm": _metric_stats("rpm"),
            "temperature_c": _metric_stats("temperature_c"),
            "z_rms_velocity_in_s": _metric_stats("z_rms_velocity_in_s"),
            "x_rms_velocity_in_s": _metric_stats("x_rms_velocity_in_s"),
        },
    }


class SimilarityEngine:
    def __init__(self) -> None:
        self.dataset = load_dataset()

    def find_similar(self, event_payload: dict[str, Any], k: int | None = None, db: Session | None = None) -> dict[str, Any]:
        target_k = max(1, k or settings.similarity_k)
        query_raw = _build_query_features(event_payload, self.dataset)
        query_scaled = _scale_query(query_raw, self.dataset)

        input_id = event_payload.get("id")
        input_source_id = event_payload.get("source_event_id")
        excluded_ids = {str(value) for value in (input_id, input_source_id) if value is not None and str(value).strip()}

        ranked = heapq.nsmallest(
            target_k + max(1, len(excluded_ids)),
            ((
                _distance(query_scaled, row_scaled),
                idx,
            ) for idx, row_scaled in enumerate(self.dataset.scaled_rows)),
            key=lambda item: item[0],
        )

        neighbors = []
        for distance, idx in ranked:
            row = self.dataset.rows[idx]
            if row.source_id in excluded_ids:
                continue
            neighbors.append(_neighbor_payload(row, distance))
            if len(neighbors) >= target_k:
                break

        probable_fault, probable_state, evidence = _aggregate_neighbors(neighbors)
        target_label = probable_fault or probable_state

        history = _describe_history(list(self.dataset.rows), target_label, neighbors) if target_label else {}
        documentation_entry = get_fault_entry(target_label) if probable_fault else None
        retrieved_chunks = []
        serialized_chunks = []
        if documentation_entry and documentation_entry["recommendation_supported"]:
            documents = get_documents_for_entry(documentation_entry)
            query = f"{target_label} diagnostico manutencao correcao"
            retrieved_chunks = retrieve_indexed_document_context(db, documents, query, top_k=3) if db else []
            if not retrieved_chunks:
                retrieved_chunks = retrieve_document_context(documents, query, top_k=3)
            serialized_chunks = serialize_context_chunks(retrieved_chunks)
        documentation = {
            "status": "supported",
            "fault": documentation_entry["canonical_label"],
            "documents": get_documents_for_entry(documentation_entry),
            "recommendation_available": True,
            "context_chunks": serialized_chunks,
        } if documentation_entry and documentation_entry["recommendation_supported"] else {
            "status": "documentation_not_found" if probable_fault else "not_required_for_state",
            "fault": target_label,
            "documents": [],
            "recommendation_available": False,
            "context_chunks": [],
        }

        recommendation: dict[str, Any]
        if probable_state == "operational_state":
            recommendation = {
                "status": "not_applicable_for_non_fault_state",
                "recommendation_available": False,
                "message": "O evento se parece com um estado operacional sem falha.",
            }
        else:
            recommendation = build_recommendation_for_fault(probable_fault, "Forneca orientacao inicial de manutencao.", db)

        return {
            "classification": {
                "status": "completed",
                "probable_fault": probable_fault,
                "state": probable_state,
                "evidence": evidence,
            },
            "similarity": {
                "status": "ready",
                "k": target_k,
                "neighbors": neighbors,
                "feature_columns": list(self.dataset.feature_columns),
                "metric": settings.similarity_metric,
            },
            "history": history,
            "documentation": documentation,
            "recommendation": recommendation,
        }


@lru_cache
def get_similarity_engine() -> SimilarityEngine:
    return SimilarityEngine()


def similarity_engine_health() -> str:
    try:
        dataset = load_dataset()
        return "loaded" if dataset.rows else "empty"
    except Exception:
        return "missing"

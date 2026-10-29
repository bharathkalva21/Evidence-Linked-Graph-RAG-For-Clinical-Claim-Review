"""Source-ID retrieval measures for a fully judged, frozen pinned-passage corpus.

Binary relevance means grade 2 (directly answers); grade 1 contributes only to
graded nDCG. Context measures use the complete context actually passed onward.
"""

import math


def _ratio(numerator: float, denominator: int) -> dict:
    return {"numerator": round(numerator, 6), "denominator": denominator,
            "value": round(numerator / denominator, 4) if denominator else None}


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1)
               for rank, grade in enumerate(grades, start=1))


def score_query(ordered_ids: list[str], grades: dict[str, int],
                facts: dict[str, list[str]], ks: list[int]) -> dict:
    """Score one query against all directly relevant passages in the corpus."""
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError("Retrieved source IDs must be unique and in rank order")
    if not grades or not any(grade == 2 for grade in grades.values()):
        raise ValueError("Each probe needs at least one directly relevant passage")
    if any(grade not in (1, 2) for grade in grades.values()):
        raise ValueError("Judged grades must be 1 or 2; unlisted passages have grade 0")
    if not facts or any(not sources or not set(sources) <= {
            source_id for source_id, grade in grades.items() if grade == 2}
                         for sources in facts.values()):
        raise ValueError("Every required fact needs at least one directly relevant source")
    if not ks or any(not isinstance(k, int) or k < 1 for k in ks):
        raise ValueError("K values must be positive integers")

    direct = {source_id for source_id, grade in grades.items() if grade == 2}
    ranked_grades = [grades.get(source_id, 0) for source_id in ordered_ids]
    at_k = {}
    for k in ks:
        top = ordered_ids[:k]
        found = len(direct.intersection(top))
        first_rank = next((rank for rank, source_id in enumerate(top, start=1)
                           if source_id in direct), None)
        ideal = _dcg(sorted(grades.values(), reverse=True)[:k])
        gain = _dcg(ranked_grades[:k])
        at_k[str(k)] = {
            "precision": _ratio(found, k),
            "recall": _ratio(found, len(direct)),
            "hit": int(found > 0),
            "reciprocal_rank": round(1 / first_rank, 6) if first_rank else 0.0,
            "ndcg": round(gain / ideal, 6) if ideal else None,
        }
    retrieved = set(ordered_ids)
    direct_count = len(direct & retrieved)
    covered_facts = sum(bool(set(sources) & retrieved) for sources in facts.values())
    return {
        "retrieved_count": len(ordered_ids),
        "directly_relevant_in_corpus": len(direct),
        "required_fact_count": len(facts),
        "at_k": at_k,
        "context_relevance": _ratio(direct_count, len(ordered_ids)),
        "context_recall": _ratio(covered_facts, len(facts)),
    }


def aggregate(query_scores: list[dict], ks: list[int]) -> dict:
    if not query_scores:
        raise ValueError("At least one scored query is required")
    n = len(query_scores)
    at_k = {}
    for k in ks:
        key = str(k)
        rows = [item["at_k"][key] for item in query_scores]
        at_k[key] = {
            "precision": _ratio(sum(row["precision"]["numerator"] for row in rows), k * n),
            "recall_micro": _ratio(sum(row["recall"]["numerator"] for row in rows),
                                    sum(row["recall"]["denominator"] for row in rows)),
            "recall_macro": _ratio(sum(row["recall"]["value"] for row in rows), n),
            "hit_rate": _ratio(sum(row["hit"] for row in rows), n),
            "mrr": _ratio(sum(row["reciprocal_rank"] for row in rows), n),
            "ndcg": _ratio(sum(row["ndcg"] for row in rows), n),
        }
    return {
        "query_count": n,
        "at_k": at_k,
        "context_relevance": _ratio(sum(item["context_relevance"]["numerator"] for item in query_scores),
                                    sum(item["context_relevance"]["denominator"] for item in query_scores)),
        "context_recall": _ratio(sum(item["context_recall"]["numerator"] for item in query_scores),
                                 sum(item["context_recall"]["denominator"] for item in query_scores)),
        "context_relevance_macro": _ratio(sum(item["context_relevance"]["value"] or 0
                                              for item in query_scores), n),
        "context_recall_macro": _ratio(sum(item["context_recall"]["value"] for item in query_scores), n),
    }

"""Ranked retrieval measures use judged IDs, graded gains, and explicit facts."""

import math

import pytest

from evaluation.retrieval_metrics import aggregate, score_query


def test_rank_metrics_and_fact_coverage():
    grades = {"a": 2, "b": 1, "c": 2}
    facts = {"first": ["a"], "second": ["c"]}
    result = score_query(["a", "b", "c", "d"], grades, facts, [1, 2, 3, 4])
    assert result["at_k"]["1"]["precision"]["value"] == 1
    assert result["at_k"]["1"]["recall"]["value"] == 0.5
    assert result["at_k"]["1"]["hit"] == 1
    assert result["at_k"]["1"]["reciprocal_rank"] == 1
    assert result["at_k"]["1"]["ndcg"] == 1
    assert result["at_k"]["2"]["ndcg"] == pytest.approx(
        (3 + 1 / math.log2(3)) / (3 + 3 / math.log2(3)), abs=1e-6)
    assert result["at_k"]["3"]["recall"]["value"] == 1
    assert result["context_relevance"] == {"numerator": 2, "denominator": 4, "value": 0.5}
    assert result["context_recall"] == {"numerator": 2, "denominator": 2, "value": 1.0}


def test_aggregate_counts_misses_and_first_relevant_rank():
    first = score_query(["a", "x", "b"], {"a": 2}, {"fact": ["a"]}, [1, 3])
    second = score_query(["x", "y", "b"], {"b": 2}, {"fact": ["b"]}, [1, 3])
    result = aggregate([first, second], [1, 3])
    assert result["at_k"]["1"]["hit_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert result["at_k"]["1"]["precision"]["value"] == 0.5
    assert result["at_k"]["3"]["recall_micro"]["value"] == 1
    assert result["at_k"]["3"]["mrr"]["value"] == pytest.approx((1 + 1/3) / 2, abs=1e-4)
    assert result["context_relevance"]["value"] == pytest.approx(2/6, abs=1e-4)


def test_bad_relevance_and_duplicate_results_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        score_query(["a", "a"], {"a": 2}, {"fact": ["a"]}, [1])
    with pytest.raises(ValueError, match="directly relevant"):
        score_query(["a"], {"a": 1}, {"fact": ["a"]}, [1])
    with pytest.raises(ValueError, match="required fact"):
        score_query(["a"], {"a": 2}, {"fact": ["missing"]}, [1])

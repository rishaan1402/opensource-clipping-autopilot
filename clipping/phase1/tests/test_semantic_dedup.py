"""
Unit tests for clipping.phase1.semantic_dedup

The real BGE model is never loaded in these tests -- _get_embedding_model is
patched with a stub whose .encode() returns caller-controlled vectors, so
similarity outcomes are deterministic and no network/GPU access is needed.
"""

import unittest
from unittest.mock import patch

import numpy as np

from clipping.phase1.semantic_dedup import (
    deduplicate_candidates,
    find_semantic_duplicates,
)


class _StubModel:
    """Maps each input text to a fixed vector via an explicit lookup table."""

    def __init__(self, vectors_by_text):
        self.vectors_by_text = vectors_by_text

    def encode(self, texts, normalize_embeddings=True):
        return np.array([self.vectors_by_text[t] for t in texts], dtype=float)


def _patch_model(vectors_by_text):
    stub = _StubModel(vectors_by_text)
    return patch(
        "clipping.phase1.semantic_dedup._get_embedding_model",
        return_value=stub,
    )


SEGMENT_DATA = [
    {"start": 0.0, "end": 5.0, "text": "alpha content"},
    {"start": 10.0, "end": 15.0, "text": "beta content"},
    {"start": 20.0, "end": 25.0, "text": "gamma content"},
]


def _clip(start, end, viral_score):
    return {"start_time": start, "end_time": end, "viral_score": viral_score}


class TestFindSemanticDuplicates(unittest.TestCase):
    def test_fewer_than_two_candidates_returns_empty(self):
        self.assertEqual(find_semantic_duplicates([_clip(0, 5, 80)], SEGMENT_DATA), [])
        self.assertEqual(find_semantic_duplicates([], SEGMENT_DATA), [])

    def test_all_empty_text_returns_empty_without_loading_model(self):
        candidates = [_clip(100, 105, 80), _clip(200, 205, 90)]
        # No overlapping segment_data -> extract_candidate_text returns "" for both.
        with _patch_model({}) as mocked:
            result = find_semantic_duplicates(candidates, SEGMENT_DATA)
        self.assertEqual(result, [])
        mocked.assert_not_called()

    def test_near_duplicate_drops_lower_viral_score(self):
        candidates = [_clip(0, 5, 60), _clip(10, 15, 95), _clip(20, 25, 70)]
        vectors = {
            "alpha content": [1.0, 0.0],
            "beta content": [1.0, 0.0],  # identical to alpha -> duplicate pair
            "gamma content": [0.0, 1.0],  # orthogonal -> distinct
        }
        with _patch_model(vectors):
            result = find_semantic_duplicates(candidates, SEGMENT_DATA, threshold=0.92)
        # index 0 (score 60) is the lower-scoring half of the alpha/beta pair.
        self.assertEqual(result, [0])

    def test_tie_score_keeps_earlier_index(self):
        candidates = [_clip(0, 5, 80), _clip(10, 15, 80), _clip(20, 25, 70)]
        vectors = {
            "alpha content": [1.0, 0.0],
            "beta content": [1.0, 0.0],
            "gamma content": [0.0, 1.0],
        }
        with _patch_model(vectors):
            result = find_semantic_duplicates(candidates, SEGMENT_DATA, threshold=0.92)
        self.assertEqual(result, [1])

    def test_below_threshold_keeps_both(self):
        candidates = [_clip(0, 5, 60), _clip(10, 15, 95)]
        vectors = {
            "alpha content": [1.0, 0.0],
            "beta content": [0.7, 0.7],  # cosine sim < 0.92
        }
        with _patch_model(vectors):
            result = find_semantic_duplicates(candidates, SEGMENT_DATA[:2], threshold=0.92)
        self.assertEqual(result, [])

    def test_empty_text_candidate_never_dropped(self):
        candidates = [_clip(0, 5, 60), _clip(1000, 1005, 90)]  # second has no overlap -> ""
        vectors = {"alpha content": [1.0, 0.0]}
        with _patch_model(vectors):
            result = find_semantic_duplicates(candidates, SEGMENT_DATA, threshold=0.92)
        self.assertEqual(result, [])


class TestDeduplicateCandidates(unittest.TestCase):
    def test_removes_flagged_indices_without_mutating_input(self):
        candidates = [_clip(0, 5, 60), _clip(10, 15, 95), _clip(20, 25, 70)]
        original_len = len(candidates)
        vectors = {
            "alpha content": [1.0, 0.0],
            "beta content": [1.0, 0.0],
            "gamma content": [0.0, 1.0],
        }
        with _patch_model(vectors):
            result = deduplicate_candidates(candidates, SEGMENT_DATA, threshold=0.92)

        self.assertEqual(len(result), 2)
        self.assertEqual([c["viral_score"] for c in result], [95, 70])
        self.assertEqual(len(candidates), original_len)  # input untouched

    def test_no_duplicates_returns_equivalent_list(self):
        candidates = [_clip(0, 5, 60), _clip(20, 25, 70)]
        vectors = {"alpha content": [1.0, 0.0], "gamma content": [0.0, 1.0]}
        with _patch_model(vectors):
            result = deduplicate_candidates(
                candidates, [SEGMENT_DATA[0], SEGMENT_DATA[2]], threshold=0.92
            )
        self.assertEqual(result, candidates)


if __name__ == "__main__":
    unittest.main()

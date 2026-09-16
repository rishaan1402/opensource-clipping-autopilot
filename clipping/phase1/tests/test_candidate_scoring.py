"""
Unit + integration tests for clipping.phase1.candidate_scoring

Covers:
- Text extraction from segment_data (Whisper-style and YouTube-JSON3-style)
- Overlap semantics matching runner.py's original pattern
- score_candidates() weighted combination math
- Weight validation
- Field preservation (no existing keys mutated/removed)
- rank is NOT touched by score_candidates (caller's responsibility)
- Artifact writing round-trip
- Full flow: combined ranking changes with weight shifts
- Disabled-flag-equivalent path (score_candidates simply not called)
"""

import json
import os
import tempfile
import unittest

from clipping.phase1.candidate_scoring import (
    extract_candidate_text,
    build_monetization_input,
    score_candidates,
    write_candidates_artifact,
)
from clipping import metadata as metadata_mod


class TestExtractCandidateText(unittest.TestCase):
    """Test transcript text extraction for a candidate's time window."""

    def test_matches_runner_pattern_text_keyed_segments(self):
        """Whisper-style segments (with 'text' key) are extracted correctly."""
        segment_data = [
            {"start": 0.0, "end": 5.0, "text": "Intro line, not in window"},
            {"start": 10.0, "end": 15.0, "text": "This is the hook"},
            {"start": 15.0, "end": 20.0, "text": "and this is the payoff"},
            {"start": 50.0, "end": 55.0, "text": "Way later, not in window"},
        ]
        clip = {"start_time": 10.0, "end_time": 20.0}
        result = extract_candidate_text(clip, segment_data)
        self.assertEqual(result, "This is the hook and this is the payoff")

    def test_words_keyed_segments_youtube_json3_style(self):
        """YouTube JSON3 style segments (only 'words', no 'text') are joined."""
        segment_data = [
            {
                "start": 10.0,
                "end": 15.0,
                "words": [{"word": "This"}, {"word": "is"}, {"word": "the"}, {"word": "hook"}],
            },
        ]
        clip = {"start_time": 10.0, "end_time": 15.0}
        result = extract_candidate_text(clip, segment_data)
        self.assertEqual(result, "This is the hook")

    def test_partial_overlap_included(self):
        """A segment only partially overlapping the window is still included,
        matching runner.py's `seg["end"] > start and seg["start"] < end`."""
        segment_data = [
            {"start": 8.0, "end": 12.0, "text": "Straddles the start boundary"},
            {"start": 18.0, "end": 22.0, "text": "Straddles the end boundary"},
        ]
        clip = {"start_time": 10.0, "end_time": 20.0}
        result = extract_candidate_text(clip, segment_data)
        self.assertIn("Straddles the start boundary", result)
        self.assertIn("Straddles the end boundary", result)

    def test_fully_outside_window_excluded(self):
        """Segments fully before or after the window are excluded."""
        segment_data = [
            {"start": 0.0, "end": 5.0, "text": "Before window"},
            {"start": 30.0, "end": 35.0, "text": "After window"},
        ]
        clip = {"start_time": 10.0, "end_time": 20.0}
        result = extract_candidate_text(clip, segment_data)
        self.assertEqual(result, "")

    def test_no_segments_returns_empty_string(self):
        """No matching segments returns empty string, not an error."""
        clip = {"start_time": 10.0, "end_time": 20.0}
        result = extract_candidate_text(clip, [])
        self.assertEqual(result, "")


class TestBuildMonetizationInput(unittest.TestCase):
    """Test the adapter shape builder."""

    def test_shape_has_exact_keys(self):
        """Returns exactly {'text', 'start', 'end'}."""
        clip = {"start_time": 10.0, "end_time": 40.0}
        segment_data = [{"start": 10.0, "end": 40.0, "text": "Stop doing this"}]
        result = build_monetization_input(clip, segment_data)
        self.assertEqual(set(result.keys()), {"text", "start", "end"})
        self.assertIsInstance(result["text"], str)
        self.assertIsInstance(result["start"], float)
        self.assertIsInstance(result["end"], float)

    def test_start_end_match_candidate_times(self):
        clip = {"start_time": 12.5, "end_time": 44.5}
        result = build_monetization_input(clip, [])
        self.assertEqual(result["start"], 12.5)
        self.assertEqual(result["end"], 44.5)


class TestScoreCandidates(unittest.TestCase):
    """Test the weighted combination and field-preservation contract."""

    def _make_candidate(self, viral_score, text, duration=32.0, extra=None):
        c = {
            "rank": 1,
            "viral_score": viral_score,
            "start_time": 0.0,
            "end_time": duration,
            "title_id": "Judul Asli",
            "title_en": "Original Title",
        }
        if extra:
            c.update(extra)
        return c, [{"start": 0.0, "end": duration, "text": text}]

    def test_combined_score_formula(self):
        """combined_score == quality_weight * quality_norm + monetization_weight * monetization_score."""
        clip, segs = self._make_candidate(80, "Stop doing this mistake")
        result = score_candidates([clip], segs, quality_weight=0.7, monetization_weight=0.3)
        item = result[0]

        expected_quality_norm = 80 / 100.0
        expected_mon = item["monetization"]["monetization_score"]
        expected_combined = 0.7 * expected_quality_norm + 0.3 * expected_mon

        self.assertAlmostEqual(item["combined_score"], expected_combined, places=9)

    def test_prosody_weight_defaults_to_zero_and_is_backward_compatible(self):
        """Omitting prosody_weight behaves exactly as before it existed."""
        clip, segs = self._make_candidate(80, "Stop doing this mistake")
        result = score_candidates([clip], segs, quality_weight=0.7, monetization_weight=0.3)
        item = result[0]

        expected_quality_norm = 80 / 100.0
        expected_mon = item["monetization"]["monetization_score"]
        expected_combined = 0.7 * expected_quality_norm + 0.3 * expected_mon

        self.assertAlmostEqual(item["combined_score"], expected_combined, places=9)
        self.assertEqual(item["scoring_weights"]["prosody"], 0.0)

    def test_prosody_weight_included_in_combined_score(self):
        """When prosody_weight > 0, prosody_score (if present) contributes to combined_score."""
        clip, segs = self._make_candidate(80, "Stop doing this mistake", extra={"prosody_score": 0.6})
        result = score_candidates(
            [clip], segs, quality_weight=0.6, monetization_weight=0.3, prosody_weight=0.1
        )
        item = result[0]

        expected_quality_norm = 80 / 100.0
        expected_mon = item["monetization"]["monetization_score"]
        expected_combined = 0.6 * expected_quality_norm + 0.3 * expected_mon + 0.1 * 0.6

        self.assertAlmostEqual(item["combined_score"], expected_combined, places=9)

    def test_prosody_score_missing_defaults_to_zero(self):
        """No 'prosody_score' key on the candidate doesn't crash; treated as 0.0."""
        clip, segs = self._make_candidate(80, "Stop doing this mistake")
        result = score_candidates(
            [clip], segs, quality_weight=0.6, monetization_weight=0.3, prosody_weight=0.1
        )
        item = result[0]

        expected_quality_norm = 80 / 100.0
        expected_mon = item["monetization"]["monetization_score"]
        expected_combined = 0.6 * expected_quality_norm + 0.3 * expected_mon

        self.assertAlmostEqual(item["combined_score"], expected_combined, places=9)

    def test_weight_validation_raises_on_bad_sum(self):
        """Weights that don't sum to 1.0 raise ValueError."""
        clip, segs = self._make_candidate(80, "Stop doing this")
        with self.assertRaises(ValueError):
            score_candidates([clip], segs, quality_weight=0.5, monetization_weight=0.6)

    def test_weight_validation_accepts_exact_one(self):
        """Weights summing to exactly 1.0 do not raise."""
        clip, segs = self._make_candidate(80, "Stop doing this")
        try:
            score_candidates([clip], segs, quality_weight=0.4, monetization_weight=0.6)
        except ValueError:
            self.fail("Valid weight sum should not raise ValueError")

    def test_preserves_original_fields(self):
        """Pre-existing keys on the candidate dict are untouched."""
        clip, segs = self._make_candidate(80, "Stop doing this", extra={"hashtags": "#python #ai"})
        original_title = clip["title_en"]
        original_hastag = clip["hashtags"]

        result = score_candidates([clip], segs)
        item = result[0]

        self.assertEqual(item["title_en"], original_title)
        self.assertEqual(item["hashtags"], original_hastag)
        self.assertEqual(item["rank"], 1)  # untouched

    def test_does_not_mutate_rank_or_reorder(self):
        """score_candidates does not re-sort the list or touch 'rank' itself."""
        klip_a, segs_a = self._make_candidate(50, "weak", extra={"rank": 1})
        klip_b, segs_b = self._make_candidate(90, "Stop doing this mistake", extra={"rank": 2})
        combined_segs = segs_a + segs_b

        result = score_candidates([klip_a, klip_b], combined_segs)

        # Order in the returned list must match input order, and rank fields
        # must be exactly as passed in (caller re-ranks, not this function).
        self.assertEqual(result[0]["rank"], 1)
        self.assertEqual(result[1]["rank"], 2)

    def test_adds_quality_score_fields(self):
        """quality_score_raw and quality_score_norm are correctly derived."""
        clip, segs = self._make_candidate(92, "Stop doing this")
        result = score_candidates([clip], segs)
        item = result[0]
        self.assertEqual(item["quality_score_raw"], 92.0)
        self.assertAlmostEqual(item["quality_score_norm"], 0.92, places=9)

    def test_scoring_weights_recorded(self):
        clip, segs = self._make_candidate(80, "Stop doing this")
        result = score_candidates([clip], segs, quality_weight=0.6, monetization_weight=0.4)
        self.assertEqual(
            result[0]["scoring_weights"],
            {"quality": 0.6, "monetization": 0.4, "prosody": 0.0},
        )

    def test_missing_viral_score_defaults_to_zero(self):
        """Candidates without a viral_score don't crash; treated as 0."""
        clip = {"rank": 1, "start_time": 0.0, "end_time": 30.0}
        segs = [{"start": 0.0, "end": 30.0, "text": "Stop doing this"}]
        result = score_candidates([clip], segs)
        self.assertEqual(result[0]["quality_score_raw"], 0.0)


class TestWriteCandidatesArtifact(unittest.TestCase):
    """Test artifact serialization round-trip."""

    def test_roundtrip(self):
        clip = {
            "rank": 1,
            "viral_score": 88,
            "quality_score_norm": 0.88,
            "monetization": {"monetization_score": 0.6, "series_potential": "high"},
            "combined_score": 0.796,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "clip_candidates.json")
            write_candidates_artifact([clip], path)

            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            self.assertEqual(loaded, [clip])

    def test_writes_unscored_candidates_too(self):
        """Artifact writer works fine on candidates with no monetization keys
        (the flag-disabled path)."""
        clip = {"rank": 1, "viral_score": 88, "title_en": "Plain"}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clip_candidates.json")
            write_candidates_artifact([clip], path)
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertNotIn("monetization", loaded[0])
            self.assertNotIn("combined_score", loaded[0])


class TestFullScoringFlowIntegration(unittest.TestCase):
    """
    Integration test: verify combined_score reordering behaves as the
    weighting math implies, using realistic runner.py-shaped candidates
    normalized through metadata.normalize_and_validate first (so this
    exercises the real upstream contract, not a hand-rolled shortcut).
    """

    def _build_raw_candidates(self):
        # Candidate A: highest viral_score, weak/rambling hook text.
        candidate_a = {
            "rank": 1,
            "viral_score": 95,
            "start_time": 0.0,
            "end_time": 90.0,  # too long, hurts monetization further
            "title_id": "Judul A",
            "title_en": "Title A",
            "description_hook": "desc",
            "description_context": "context",
            "hashtags": "#a #b",
            "keyword_tags": ["a", "b", "c", "d", "e"],
            "tiktok_title_id": "Judul A",
            "tiktok_caption_id": "Caption A",
            "tiktok_caption": "Caption A EN",
        }
        # Candidate B: lower viral_score, strong hook + optimal length.
        candidate_b = {
            "rank": 2,
            "viral_score": 70,
            "start_time": 100.0,
            "end_time": 132.0,  # 32s optimal
            "title_id": "Judul B",
            "title_en": "Title B",
            "description_hook": "desc",
            "description_context": "context",
            "hashtags": "#c #d",
            "keyword_tags": ["a", "b", "c", "d", "e"],
            "tiktok_title_id": "Judul B",
            "tiktok_caption_id": "Caption B",
            "tiktok_caption": "Caption B EN",
        }
        segment_data = [
            {
                "start": 0.0,
                "end": 90.0,
                "text": "So like um you know just rambling on and on about nothing much really",
            },
            {
                "start": 100.0,
                "end": 132.0,
                "text": "Stop making this one mistake - here is the secret fix nobody tells you",
            },
        ]
        return [candidate_a, candidate_b], segment_data

    def _rerank(self, result_json):
        """Mirror the exact re-rank-after-sort logic runner.py Step 4.5 uses."""
        ranked = sorted(result_json, key=lambda x: x["combined_score"], reverse=True)
        for idx, item in enumerate(ranked):
            item["rank"] = idx + 1
        return ranked

    def test_default_weights_quality_dominates(self):
        """At the default 0.7/0.3 split, A's much higher viral_score keeps it on top."""
        raw, segment_data = self._build_raw_candidates()
        normalized = metadata_mod.normalize_and_validate(raw)

        scored = score_candidates(normalized, segment_data, quality_weight=0.7, monetization_weight=0.3)
        ranked = self._rerank(scored)

        self.assertEqual(ranked[0]["title_en"], "Title A")

    def test_monetization_heavy_weights_flip_ranking(self):
        """Shifting weight toward monetization (0.4/0.6) lets B's strong hook overtake A."""
        raw, segment_data = self._build_raw_candidates()
        normalized = metadata_mod.normalize_and_validate(raw)

        scored = score_candidates(normalized, segment_data, quality_weight=0.4, monetization_weight=0.6)
        ranked = self._rerank(scored)

        self.assertEqual(ranked[0]["title_en"], "Title B")

    def test_all_original_metadata_fields_survive_full_flow(self):
        """After normalize -> score -> rerank, all metadata.py-enriched fields are intact."""
        raw, segment_data = self._build_raw_candidates()
        normalized = metadata_mod.normalize_and_validate(raw)
        scored = score_candidates(normalized, segment_data)
        ranked = self._rerank(scored)

        for item in ranked:
            self.assertIn("youtube_title_final", item)
            self.assertIn("youtube_description_final", item)
            self.assertIn("tiktok_caption_final", item)
            self.assertIn("monetization", item)
            self.assertIn("combined_score", item)


class TestMonetizationDisabledPath(unittest.TestCase):
    """
    Regression: when monetization scoring is disabled, candidate ordering
    must be byte-identical to calling only metadata.normalize_and_validate
    (i.e. score_candidates is simply never invoked -- verified here by
    confirming normalize_and_validate's own ordering is stable and
    untouched by anything in this module).
    """

    def test_normalize_and_validate_order_unaffected_by_this_module_import(self):
        raw = [
            {"rank": 1, "viral_score": 50, "start_time": 0, "end_time": 10,
             "title_id": "A", "title_en": "A EN", "description_hook": "d",
             "description_context": "c", "hashtags": "#a #b", "keyword_tags": ["a", "b", "c", "d", "e"],
             "tiktok_title_id": "A", "tiktok_caption_id": "A", "tiktok_caption": "A EN"},
            {"rank": 2, "viral_score": 90, "start_time": 20, "end_time": 30,
             "title_id": "B", "title_en": "B EN", "description_hook": "d",
             "description_context": "c", "hashtags": "#a #b", "keyword_tags": ["a", "b", "c", "d", "e"],
             "tiktok_title_id": "B", "tiktok_caption_id": "B", "tiktok_caption": "B EN"},
        ]
        result = metadata_mod.normalize_and_validate(raw)
        # Pure viral_score ordering: B (90) before A (50).
        self.assertEqual(result[0]["title_en"], "B EN")
        self.assertEqual(result[1]["title_en"], "A EN")
        self.assertNotIn("monetization", result[0])
        self.assertNotIn("combined_score", result[0])


if __name__ == "__main__":
    unittest.main()

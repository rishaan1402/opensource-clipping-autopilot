"""
Candidate Scoring Adapter

Bridges the Gemini/NVIDIA-shaped clip candidates produced by
`clipping.engine.analyze_with_ai` (as normalized by
`clipping.metadata.normalize_and_validate`) to the generic
`{text, start, end}` contract expected by `clipping.phase1.monetization`.

`monetization.py` is intentionally pipeline-agnostic (independently tested
against a plain segment schema); this module is the one integration point
that knows about `runner.py`'s actual candidate shape (`start_time`,
`end_time`, `viral_score`, etc.) and does the text-extraction + weighted
combination + artifact writing specific to that pipeline.

has_face / has_motion are populated by clipping.runner (via
clipping.studio.face_detection.quick_face_motion_probe) directly onto each
candidate dict before score_candidates() is called, and passed through here
unchanged. When a candidate has neither key set — e.g. this module is used
standalone, without that probe having run — MonetizationScorer.score_clip
treats them as genuinely unknown, not as confirmed-absent.
"""

import json
import os
from typing import Dict, List

from .monetization import MonetizationScorer


def extract_candidate_text(clip: Dict, segment_data: List[Dict]) -> str:
    """
    Build transcript text for a candidate's [start_time, end_time] window.

    Reuses the exact overlap + text-join pattern already used for the
    voice-over script step in clipping/runner.py (lines ~190-198): a segment
    is included if it overlaps the window at all (segment end > window start
    AND segment start < window end), not only if fully contained. Supports
    both Whisper-style segments (`text` key) and YouTube JSON3 segments
    (`words: [{word: ...}, ...]`, no top-level `text`).

    Args:
        clip: Candidate dict with 'start_time' / 'end_time' keys.
        segment_data: Transcript segments from Whisper or YouTube JSON3.

    Returns:
        Joined transcript text for the window (empty string if no overlap).
    """
    start = float(clip.get("start_time", 0.0))
    end = float(clip.get("end_time", 0.0))

    lines = []
    for seg in segment_data:
        seg_end = float(seg.get("end", 0.0))
        seg_start = float(seg.get("start", 0.0))
        if seg_end > start and seg_start < end:
            seg_text = seg.get("text") or " ".join(
                w["word"] for w in seg.get("words", [])
            )
            if seg_text:
                lines.append(seg_text)

    return " ".join(lines).strip()


def build_monetization_input(clip: Dict, segment_data: List[Dict]) -> Dict:
    """
    Build the {'text', 'start', 'end'} dict MonetizationScorer expects.

    Args:
        clip: Candidate dict with 'start_time' / 'end_time' keys.
        segment_data: Transcript segments.

    Returns:
        {'text': str, 'start': float, 'end': float}
    """
    return {
        "text": extract_candidate_text(clip, segment_data),
        "start": float(clip.get("start_time", 0.0)),
        "end": float(clip.get("end_time", 0.0)),
        "has_face": clip.get("has_face"),
        "has_motion": clip.get("has_motion"),
    }


def score_candidates(
    result_json: List[Dict],
    segment_data: List[Dict],
    quality_weight: float = 0.7,
    monetization_weight: float = 0.3,
    prosody_weight: float = 0.0,
) -> List[Dict]:
    """
    Attach monetization scoring + combined ranking score to each candidate.

    Mutates and returns the same list (in the original order given — this
    function does NOT re-sort or reassign 'rank'; that is the caller's
    responsibility, mirroring how clipping.metadata.normalize_and_validate
    already owns its own sort-then-reassign-rank step). Every pre-existing
    key on each candidate dict is left untouched; only new keys are added:

        quality_score_raw   -- original viral_score (1-100), untouched
        quality_score_norm  -- viral_score / 100.0
        monetization        -- full MonetizationMetrics dict (see
                                monetization.MonetizationScorer.batch_score)
        combined_score      -- quality_weight * quality_norm
                                + monetization_weight * monetization_score
                                + prosody_weight * prosody_score
        scoring_weights     -- {'quality': quality_weight,
                                 'monetization': monetization_weight,
                                 'prosody': prosody_weight}

    Args:
        result_json: Candidate list as produced by
            clipping.metadata.normalize_and_validate (each item must already
            have a numeric 'viral_score').
        segment_data: Transcript segments used to extract per-candidate text.
        quality_weight: Weight (0-1) for the existing AI viral_score.
        monetization_weight: Weight (0-1) for the monetization score.
        prosody_weight: Weight (0-1) for the 'prosody_score' field, if
            clipping.phase1.prosody_scoring.score_candidates_prosody was run
            beforehand. Defaults to 0.0 (no-op, fully backward compatible)
            since prosody scoring is opt-in; reads
            clip.get('prosody_score', 0.0) defensively so this never raises
            even if that field is absent.

    Returns:
        The same list, each item enriched with the fields above.

    Raises:
        ValueError: if quality_weight + monetization_weight + prosody_weight
            does not sum to 1.0 within a 1e-6 tolerance. This is a second
            guard in addition to the CLI-level validation in
            clipping.config.build_config, since this function can be called
            directly (tests, notebooks) without going through the CLI.
    """
    total_weight = quality_weight + monetization_weight + prosody_weight
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(
            f"quality_weight + monetization_weight + prosody_weight must sum to 1.0, "
            f"got {quality_weight} + {monetization_weight} + {prosody_weight} = {total_weight}"
        )

    for clip in result_json:
        mon_input = build_monetization_input(clip, segment_data)
        metrics = MonetizationScorer.score_clip(mon_input)

        viral_score = float(clip.get("viral_score", 0))
        quality_norm = viral_score / 100.0
        prosody_norm = float(clip.get("prosody_score", 0.0))

        clip["quality_score_raw"] = viral_score
        clip["quality_score_norm"] = quality_norm
        clip["monetization"] = {
            "hook_strength": metrics.hook_strength,
            "vvsa_score": metrics.vvsa_score,
            "retention_score": metrics.retention_score,
            "optimal_length": metrics.optimal_length,
            "structure_score": metrics.structure_score,
            "monetization_score": metrics.monetization_score,
            "series_potential": metrics.series_potential,
            "has_face": metrics.has_face,
            "has_motion": metrics.has_motion,
            "recommendations": metrics.recommendations,
        }
        clip["combined_score"] = (
            quality_weight * quality_norm
            + monetization_weight * metrics.monetization_score
            + prosody_weight * prosody_norm
        )
        clip["scoring_weights"] = {
            "quality": quality_weight,
            "monetization": monetization_weight,
            "prosody": prosody_weight,
        }

    return result_json


def write_candidates_artifact(result_json: List[Dict], path: str) -> None:
    """
    Write the (scored or unscored) candidate list to an inspectable JSON
    artifact, following the same convention as gemini_response.json and
    metadata_preview.json in clipping/runner.py.

    Args:
        result_json: Candidate list, scored or not.
        path: Destination file path (typically
            os.path.join(cfg.outputs_dir, "clip_candidates.json")).
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

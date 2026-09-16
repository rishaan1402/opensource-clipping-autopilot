"""
Semantic Dedup (BGE)

Uses BGE sentence embeddings to catch AI-selected candidates that are secretly
the same moment restated -- something hash-based dedup
(clipping.phase1.deduplication) can't see, since that only matches identical
re-uploads, not semantic overlap within one video's own candidate set.

Deliberately narrow, not a general-purpose dedup library: it knows about this
pipeline's candidate shape (start_time/end_time, viral_score) the same way
clipping.phase1.candidate_scoring does, and reuses its text-extraction logic.
"""

from typing import Dict, List

from .candidate_scoring import extract_candidate_text

DEFAULT_BGE_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_SIMILARITY_THRESHOLD = 0.92

_model_cache: Dict[str, object] = {}


def _get_embedding_model(model_name: str):
    """Lazily load and cache a sentence-transformers model by name.

    Kept as a module-level cache (not per-call) since this runs once per
    video but loading the model itself takes real time and VRAM -- repeated
    calls within one process should reuse the already-loaded model.
    """
    if model_name not in _model_cache:
        from sentence_transformers import SentenceTransformer

        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def find_semantic_duplicates(
    candidates: List[Dict],
    segment_data: List[Dict],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    model_name: str = DEFAULT_BGE_MODEL,
) -> List[int]:
    """
    Find indices (into `candidates`) that are near-duplicates of an earlier,
    higher-scoring candidate in the same list.

    For each pair whose cosine similarity crosses `threshold`, the
    lower-`viral_score` candidate is marked for drop (ties keep the
    earlier-indexed one, i.e. the AI's original preferred ordering).
    Candidates with no extractable transcript text are never compared --
    two independently empty strings would otherwise embed identically and
    look like a false-positive duplicate.

    Args:
        candidates: Candidate list with 'start_time'/'end_time'/'viral_score'.
        segment_data: Transcript segments used to extract per-candidate text.
        threshold: Cosine similarity (0-1) above which two candidates are
            treated as duplicates. Higher = stricter (fewer drops).
        model_name: sentence-transformers-compatible BGE model name.

    Returns:
        Sorted list of indices to drop.
    """
    if len(candidates) < 2:
        return []

    texts = [extract_candidate_text(c, segment_data) for c in candidates]
    non_empty_indices = [i for i, t in enumerate(texts) if t.strip()]
    if len(non_empty_indices) < 2:
        return []

    model = _get_embedding_model(model_name)
    embeddings = model.encode(
        [texts[i] for i in non_empty_indices],
        normalize_embeddings=True,
    )

    import numpy as np

    sims = np.asarray(embeddings) @ np.asarray(embeddings).T  # cosine, since normalized

    to_drop = set()
    for a, i in enumerate(non_empty_indices):
        if i in to_drop:
            continue
        for b in range(a + 1, len(non_empty_indices)):
            j = non_empty_indices[b]
            if j in to_drop:
                continue
            if sims[a, b] >= threshold:
                score_i = float(candidates[i].get("viral_score", 0))
                score_j = float(candidates[j].get("viral_score", 0))
                if score_j > score_i:
                    to_drop.add(i)
                    break
                to_drop.add(j)

    return sorted(to_drop)


def deduplicate_candidates(
    candidates: List[Dict],
    segment_data: List[Dict],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    model_name: str = DEFAULT_BGE_MODEL,
) -> List[Dict]:
    """
    Return a new candidate list with semantic near-duplicates removed.

    Does not mutate `candidates`, does not re-sort or reassign 'rank' --
    mirrors score_candidates()'s convention of leaving ranking to the caller.
    """
    if len(candidates) < 2:
        return list(candidates)

    drop_indices = find_semantic_duplicates(candidates, segment_data, threshold, model_name)
    if not drop_indices:
        return list(candidates)

    drop_set = set(drop_indices)
    return [c for i, c in enumerate(candidates) if i not in drop_set]

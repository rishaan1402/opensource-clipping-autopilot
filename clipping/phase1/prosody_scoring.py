"""
Whisper-Prosody Scoring

Whisper is already run for transcription (clipping.engine.transcribe_video),
but only its *text* output is used downstream -- the audio signal itself is
thrown away. This module reads it back for each AI-selected candidate window
and extracts a cheap, well-established proxy for "this moment carries
audible emphasis/excitement": pitch variance, energy variance, energy-peak
spikiness, and pause ratio. No model, just signal processing (librosa) on
the audio the pipeline already has on disk.

This is intentionally a soft, heuristic signal (see clipping.phase1.monetization
and clipping.phase1.candidate_scoring for the existing quality/monetization
scoring this feeds into) -- any window that can't be scored (silent, too
short, unreadable) degrades to neutral/zero rather than raising, since a
missing prosody signal should never block clip selection.
"""

from typing import Dict, List

_PROSODY_FEATURE_KEYS = ("pitch_variance", "energy_variance", "energy_peak_ratio", "pause_ratio")

_EMPTY_FEATURES = {k: 0.0 for k in _PROSODY_FEATURE_KEYS}


def extract_window_audio(audio_path: str, start: float, end: float, sr: int = 16000):
    """Load the [start, end) window of `audio_path` as a mono waveform at `sr` Hz."""
    import librosa

    duration = max(0.01, end - start)
    y, _ = librosa.load(audio_path, sr=sr, offset=max(0.0, start), duration=duration)
    return y, sr


def score_window_prosody(audio_path: str, start: float, end: float) -> Dict[str, float]:
    """
    Compute raw prosody features for one [start, end) window.

    Returns:
        {
          "pitch_variance": std of estimated f0 over voiced frames,
          "energy_variance": std of RMS energy across the window,
          "energy_peak_ratio": max(RMS) / mean(RMS) -- spikiness,
          "pause_ratio": fraction of frames below a silence threshold,
        }
        All-zero (not an exception) if the window is empty, silent, or the
        audio can't be read -- see module docstring.
    """
    try:
        import numpy as np
        import librosa

        y, sr = extract_window_audio(audio_path, start, end)
    except Exception:
        # Covers a missing librosa install as well as an unreadable/missing
        # audio file -- both degrade to neutral rather than raising.
        return dict(_EMPTY_FEATURES)

    if y.size == 0:
        return dict(_EMPTY_FEATURES)

    rms = librosa.feature.rms(y=y)[0]
    if rms.size == 0:
        return dict(_EMPTY_FEATURES)

    mean_rms = float(np.mean(rms))
    energy_variance = float(np.std(rms))
    energy_peak_ratio = float(np.max(rms)) / mean_rms if mean_rms > 1e-9 else 0.0

    silence_threshold = mean_rms * 0.1
    pause_ratio = float(np.mean(rms < silence_threshold))

    pitch_variance = 0.0
    try:
        f0, voiced_flag, _ = librosa.pyin(
            y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
        )
        if voiced_flag is not None:
            voiced_f0 = f0[voiced_flag]
            if voiced_f0.size > 1:
                pitch_variance = float(np.std(voiced_f0))
    except Exception:
        pass

    return {
        "pitch_variance": pitch_variance,
        "energy_variance": energy_variance,
        "energy_peak_ratio": energy_peak_ratio,
        "pause_ratio": pause_ratio,
    }


def _min_max_normalize(values: List[float]) -> List[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)  # no variation across the batch -> neutral, not 0
    return [(v - lo) / (hi - lo) for v in values]


def score_candidates_prosody(
    candidates: List[Dict],
    audio_path: str,
    weights: Dict[str, float] | None = None,
) -> List[Dict]:
    """
    Attach prosody features + a normalized 0-1 'prosody_score' to each
    candidate, mutating and returning the same list (mirrors
    clipping.phase1.candidate_scoring.score_candidates' convention).

    Each raw feature is min-max normalized across this candidate batch
    (not against a fixed global scale) since absolute energy/pitch depends
    heavily on the source video's mic/loudness -- what matters is which
    candidates stand out *relative to the others from the same video*.

    Args:
        candidates: Candidate list with 'start_time'/'end_time' keys.
        audio_path: Path to the source audio/video file (anything librosa
            can open) that the candidate windows are relative to.
        weights: Optional override for combining the four normalized
            features into 'prosody_score'. Defaults favor pitch/energy
            variance (the clearest "emphasis" signals) over peak spikiness
            and pause ratio (pause_ratio is inverted: more pauses -> less
            exciting). Keys: pitch, energy, peak, pause. Need not sum to 1.

    Returns:
        The same list, each item enriched with 'prosody' (raw features)
        and 'prosody_score' (float, 0-1).
    """
    if weights is None:
        weights = {"pitch": 0.35, "energy": 0.35, "peak": 0.20, "pause": 0.10}

    if not candidates:
        return candidates

    raw = [
        score_window_prosody(audio_path, float(c.get("start_time", 0.0)), float(c.get("end_time", 0.0)))
        for c in candidates
    ]

    pitch_norm = _min_max_normalize([r["pitch_variance"] for r in raw])
    energy_norm = _min_max_normalize([r["energy_variance"] for r in raw])
    peak_norm = _min_max_normalize([r["energy_peak_ratio"] for r in raw])
    pause_norm = _min_max_normalize([r["pause_ratio"] for r in raw])

    for i, clip in enumerate(candidates):
        prosody_score = (
            weights["pitch"] * pitch_norm[i]
            + weights["energy"] * energy_norm[i]
            + weights["peak"] * peak_norm[i]
            + weights["pause"] * (1.0 - pause_norm[i])  # more pause -> less exciting
        )
        clip["prosody"] = raw[i]
        clip["prosody_score"] = prosody_score

    return candidates

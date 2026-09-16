"""
Boundary Correction

The AI prompt (clipping.engine.get_analysis_prompt) already asks the model
not to cut a clip before a thought finishes, but nothing verifies that
against the actual transcript — the model's start_time/end_time are used
as-is by clipping.studio.process_clip. This module is that missing check:
it uses Whisper's word-level timestamps (already produced by
clipping.engine.transcribe_video, one dict per word with 'start'/'end') to
detect an end_time that lands mid-word or mid-sentence, and extends it to
the next sentence-ending word when that's possible within the pipeline's
own duration ceiling.
"""

from typing import Dict, List, Optional

_TERMINAL_CHARS = ".!?"
_TRAILING_STRIP_CHARS = "\"'”’)]"


def _ends_sentence(word_text: str) -> bool:
    """Does this word (as transcribed, with its trailing punctuation) look
    like the end of a sentence? Strips a trailing quote/paren first so
    '"done."' and 'done.”' both count."""
    trailing = (word_text or "").strip().rstrip(_TRAILING_STRIP_CHARS)
    return bool(trailing) and trailing[-1] in _TERMINAL_CHARS


def _flatten_words(segment_data: List[Dict]) -> List[Dict]:
    """Whisper's word-level segments (clipping.engine.transcribe_video)
    group words into chunks of `max_words_per_subtitle` under a 'words' key
    — flatten back into one chronological word list. Segments without a
    'words' key (e.g. YouTube JSON3 subtitles, which are line-level only)
    contribute nothing here; callers should skip correction when this comes
    back empty rather than guess sentence boundaries from line text alone."""
    words = []
    for seg in segment_data:
        for w in seg.get("words", []):
            if "start" in w and "end" in w and "word" in w:
                words.append(w)
    words.sort(key=lambda w: w["start"])
    return words


def correct_clip_boundaries(
    result_json: List[Dict],
    segment_data: List[Dict],
    max_duration: float = 179.0,
    max_extension_seconds: float = 12.0,
    end_padding: float = 0.2,
) -> List[Dict]:
    """
    Check each candidate's end_time (and, lightly, start_time) against
    Whisper's word timestamps and correct mid-sentence cuts.

    For each clip:
      1. If end_time cuts off mid-word, or the last word inside the window
         doesn't end on terminal punctuation (. ! ?), search forward for the
         next sentence-ending word and extend end_time just past it —
         bounded by `max_extension_seconds` (a bad AI pick shouldn't balloon
         the clip) and `max_duration` (the pipeline's own ceiling, so this
         never produces a clip main.py would otherwise reject).
      2. If no such word exists within those bounds, end_time is left
         unchanged but the clip is tagged with 'boundary_issue' so the
         problem is visible in clip_candidates.json / render_manifest.json
         instead of silently shipping a bad cut.
      3. If start_time lands inside a word rather than at its boundary, it's
         snapped back to that word's start (also bounded by max_duration).

    Mutates and returns the same list. No-ops (returns result_json
    unchanged) if segment_data has no word-level timestamps at all.
    """
    words = _flatten_words(segment_data)
    if not words:
        return result_json

    for clip in result_json:
        start = float(clip.get("start_time", 0.0))
        end = float(clip.get("end_time", 0.0))
        if end <= start:
            continue

        overlapping = [
            (i, w) for i, w in enumerate(words) if w["start"] < end and w["end"] > start
        ]
        if not overlapping:
            continue

        last_idx, last_word = overlapping[-1]
        cuts_mid_word = last_word["end"] > end + 0.02
        complete = (not cuts_mid_word) and _ends_sentence(last_word["word"])

        if not complete:
            extended_end: Optional[float] = None
            for w in words[last_idx:]:
                candidate_end = w["end"] + end_padding
                if candidate_end - end > max_extension_seconds:
                    break
                if candidate_end - start > max_duration:
                    break
                if _ends_sentence(w["word"]):
                    extended_end = candidate_end
                    break

            if extended_end is not None and extended_end > end:
                added = round(extended_end - end, 2)
                clip["end_time"] = round(extended_end, 2)
                clip["boundary_corrected"] = True
                clip["boundary_correction_note"] = (
                    f"end_time extended {added}s to finish the sentence"
                )
                print(
                    f"   ✂️ Rank {clip.get('rank', '?')}: extended end_time by "
                    f"{added}s to avoid a mid-sentence cutoff."
                )
            else:
                clip["boundary_issue"] = "ends_mid_sentence_uncorrectable"
                print(
                    f"   ⚠️ Rank {clip.get('rank', '?')}: transcript suggests this "
                    f"clip cuts off mid-sentence; couldn't extend within duration/lookahead limits."
                )

        first_idx, first_word = overlapping[0]
        if first_word["start"] < start:
            new_start = first_word["start"]
            if clip.get("end_time", end) - new_start <= max_duration:
                clip["start_time"] = round(new_start, 2)

    return result_json

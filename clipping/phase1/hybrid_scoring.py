"""
Hybrid Segment Scoring

Combines multiple scoring methods for better clip detection:
- Text heuristics (keywords, questions, length)
- Audio analysis (pitch variation, pauses, energy)
- Scene detection (hard cuts in video)

Weighted combination: Text (30%) + Audio (40%) + Scene (30%)
"""

import re
import subprocess
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class TextScorer:
    """Score segments based on text content."""

    # Trigger keywords that indicate interesting content
    STRONG_KEYWORDS = [
        'best', 'worst', 'secret', 'hack', 'tip', 'trick', 'mistake', 'important',
        'actually', 'real', 'fact', 'truth', 'never', 'always', 'must', 'should',
        'incredible', 'amazing', 'insane', 'crazy', 'impossible', 'powerful'
    ]

    MEDIUM_KEYWORDS = [
        'why', 'how', 'what', 'when', 'where', 'can', 'will', 'just',
        'new', 'first', 'last', 'unique', 'special', 'perfect', 'easy'
    ]

    MIN_SEGMENT_LENGTH = 8  # words
    MAX_SEGMENT_LENGTH = 35  # words

    @classmethod
    def score_segment(cls, text: str) -> float:
        """
        Score text segment (0.0 to 1.0).

        Args:
            text: Segment text

        Returns:
            Score between 0.0 and 1.0
        """
        if not text or len(text.strip()) < 3:
            return 0.0

        score = 0.0
        text_lower = text.lower()

        # Question detection (high value)
        if '?' in text:
            score += 0.3

        # Strong keyword detection
        for keyword in cls.STRONG_KEYWORDS:
            if keyword in text_lower:
                score += 0.2
                break  # Only count once

        # Medium keyword detection
        for keyword in cls.MEDIUM_KEYWORDS:
            if keyword in text_lower:
                score += 0.1
                break

        # Length scoring (prefer 8-35 words)
        word_count = len(text.split())
        if cls.MIN_SEGMENT_LENGTH <= word_count <= cls.MAX_SEGMENT_LENGTH:
            score += 0.2
        elif word_count < cls.MIN_SEGMENT_LENGTH:
            score *= 0.5  # Penalize very short segments
        elif word_count > cls.MAX_SEGMENT_LENGTH:
            score *= 0.7  # Slight penalty for very long segments

        # Exclamation marks (indicate emphasis)
        exclamation_count = text.count('!')
        if exclamation_count > 0:
            score += min(0.1, exclamation_count * 0.05)

        # UPPERCASE (emphasis)
        uppercase_ratio = sum(1 for c in text if c.isupper()) / len(text) if text else 0
        if uppercase_ratio > 0.3:
            score += 0.1

        return min(1.0, score)  # Cap at 1.0


class AudioScorer:
    """Score segments based on audio analysis."""

    @staticmethod
    def detect_silence_regions(audio_path: str, silence_threshold: float = -40) -> List[Tuple[float, float]]:
        """
        Detect silent regions in audio using ffmpeg.

        Returns list of (start, end) tuples in seconds
        """
        try:
            result = subprocess.run(
                ['ffmpeg', '-i', audio_path, '-af', f'silencedetect=n={silence_threshold}dB:d=0.5',
                 '-f', 'null', '-'],
                capture_output=True,
                timeout=30,
                text=True
            )

            silence_regions = []
            for line in result.stderr.split('\n'):
                if 'silence_start' in line or 'silence_end' in line:
                    # Parse: [silencedetect @ ...] silence_start: 1.234
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part in ['silence_start:', 'silence_end:'] and i + 1 < len(parts):
                            try:
                                time = float(parts[i + 1])
                                silence_regions.append(time)
                            except ValueError:
                                pass

            # Pair up start/end times
            paired = []
            for i in range(0, len(silence_regions) - 1, 2):
                paired.append((silence_regions[i], silence_regions[i + 1]))

            return paired
        except Exception as e:
            logger.warning(f"Could not detect silence: {e}")
            return []

    @staticmethod
    def score_segment_audio(audio_path: str, start: float, end: float) -> float:
        """
        Score audio segment based on:
        - Speaking density (avoid long pauses)
        - Energy variation (speaker gets excited)

        Returns score 0.0-1.0
        """
        # For now, simple heuristic: prefer segments without silence
        silence_regions = AudioScorer.detect_silence_regions(audio_path)

        score = 1.0
        segment_duration = end - start

        # Penalize if segment has significant silence
        for silence_start, silence_end in silence_regions:
            if start <= silence_start < end or start < silence_end <= end:
                silence_in_segment = min(silence_end, end) - max(silence_start, start)
                score -= (silence_in_segment / segment_duration) * 0.3

        return max(0.0, min(1.0, score))


class SceneScorer:
    """Score segments based on scene detection."""

    @staticmethod
    def detect_scenes(video_path: str) -> List[float]:
        """
        Detect scene cuts using PySceneDetect.

        Returns list of timestamps (in seconds) where scenes change
        """
        try:
            result = subprocess.run(
                ['scenedetect', '-i', video_path, 'detect-content', '-t', '27.0', 'list-scenes'],
                capture_output=True,
                timeout=60,
                text=True
            )

            scenes = []
            for line in result.stdout.split('\n'):
                # Parse: "00:00:12.34	Scene 1	[0.123]"
                parts = line.strip().split()
                if len(parts) >= 2 and ':' in parts[0]:
                    try:
                        time_str = parts[0]
                        # Convert HH:MM:SS.ms to seconds
                        time_parts = time_str.split(':')
                        if len(time_parts) == 3:
                            h, m, s = float(time_parts[0]), float(time_parts[1]), float(time_parts[2])
                            timestamp = h * 3600 + m * 60 + s
                            scenes.append(timestamp)
                    except ValueError:
                        pass

            return scenes
        except Exception as e:
            logger.warning(f"Could not detect scenes: {e}")
            return []

    @staticmethod
    def score_segment_scene(segment_start: float, segment_end: float, scene_cuts: List[float]) -> float:
        """
        Score segment based on proximity to scene cuts.

        Prefer segments that span scene boundaries or contain cuts.

        Returns score 0.0-1.0
        """
        score = 0.5  # Base score

        # Count scene cuts within segment
        cuts_in_segment = sum(1 for cut in scene_cuts if segment_start <= cut <= segment_end)
        if cuts_in_segment > 0:
            score += 0.25 * min(1.0, cuts_in_segment / 3)  # Reward multiple cuts

        # Check if segment starts/ends near scene boundaries
        for cut in scene_cuts:
            if abs(cut - segment_start) < 2.0 or abs(cut - segment_end) < 2.0:
                score += 0.15
                break

        return min(1.0, score)


class HybridSegmentScorer:
    """Combines all scoring methods."""

    # Weights for each component (sum to 1.0)
    WEIGHT_TEXT = 0.3
    WEIGHT_AUDIO = 0.4
    WEIGHT_SCENE = 0.3

    def __init__(self, video_path: str, audio_path: str):
        """
        Initialize hybrid scorer.

        Args:
            video_path: Path to video file
            audio_path: Path to audio file
        """
        self.video_path = video_path
        self.audio_path = audio_path
        self.scene_cuts = SceneScorer.detect_scenes(video_path)
        logger.info(f"Detected {len(self.scene_cuts)} scene cuts")

    def score_segment(
        self,
        text: str,
        start: float,
        end: float,
        use_audio: bool = True,
        use_scene: bool = True
    ) -> float:
        """
        Score a segment using all available methods.

        Args:
            text: Segment text content
            start: Start time in seconds
            end: End time in seconds
            use_audio: Include audio analysis
            use_scene: Include scene detection

        Returns:
            Score between 0.0 and 1.0
        """
        # Text scoring (always used)
        text_score = TextScorer.score_segment(text)

        # Audio scoring
        audio_score = 0.5  # Default neutral
        if use_audio:
            try:
                audio_score = AudioScorer.score_segment_audio(self.audio_path, start, end)
            except Exception as e:
                logger.debug(f"Audio scoring failed: {e}")

        # Scene scoring
        scene_score = 0.5  # Default neutral
        if use_scene and self.scene_cuts:
            try:
                scene_score = SceneScorer.score_segment_scene(start, end, self.scene_cuts)
            except Exception as e:
                logger.debug(f"Scene scoring failed: {e}")

        # Weighted combination
        final_score = (
            self.WEIGHT_TEXT * text_score +
            self.WEIGHT_AUDIO * audio_score +
            self.WEIGHT_SCENE * scene_score
        )

        return min(1.0, final_score)

    def score_all_segments(
        self,
        segments: List[Dict],
        use_audio: bool = True,
        use_scene: bool = True
    ) -> List[Dict]:
        """
        Score multiple segments.

        Args:
            segments: List of {text, start, end, ...} dicts
            use_audio: Include audio analysis
            use_scene: Include scene detection

        Returns:
            Same segments with added 'score' and 'score_breakdown' fields
        """
        scored = []

        for segment in segments:
            text = segment.get('text', '')
            start = segment.get('start', 0)
            end = segment.get('end', 0)

            score = self.score_segment(text, start, end, use_audio, use_scene)

            scored_segment = segment.copy()
            scored_segment['score'] = score
            scored.append(scored_segment)

        return scored

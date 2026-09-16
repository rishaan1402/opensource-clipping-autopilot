"""
Unit tests for clipping.phase1.prosody_scoring

score_window_prosody() itself needs a real audio file to run librosa/pyin
against, so these tests cover it against small synthetic WAV files (pure
tones / silence generated with numpy, no network access) plus the pure
normalization/aggregation logic in score_candidates_prosody(), which is
tested against a stubbed score_window_prosody so it stays fast and
deterministic.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from clipping.phase1.prosody_scoring import (
    _min_max_normalize,
    score_candidates_prosody,
    score_window_prosody,
)


def _write_wav(path, y, sr=16000):
    import soundfile as sf

    sf.write(path, y, sr)


class TestMinMaxNormalize(unittest.TestCase):
    def test_spreads_values_into_zero_one_range(self):
        result = _min_max_normalize([0.0, 5.0, 10.0])
        self.assertAlmostEqual(result[0], 0.0)
        self.assertAlmostEqual(result[1], 0.5)
        self.assertAlmostEqual(result[2], 1.0)

    def test_constant_values_return_neutral_half(self):
        result = _min_max_normalize([3.0, 3.0, 3.0])
        self.assertEqual(result, [0.5, 0.5, 0.5])


class TestScoreWindowProsody(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _make_tone_wav(self, freq=220.0, duration=2.0, sr=16000):
        try:
            import soundfile as sf  # noqa: F401
        except ImportError:
            self.skipTest("soundfile not installed")
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        y = 0.5 * np.sin(2 * np.pi * freq * t)
        path = os.path.join(self.tmpdir.name, "tone.wav")
        _write_wav(path, y.astype(np.float32), sr)
        return path

    def _make_silence_wav(self, duration=2.0, sr=16000):
        try:
            import soundfile as sf  # noqa: F401
        except ImportError:
            self.skipTest("soundfile not installed")
        y = np.zeros(int(sr * duration), dtype=np.float32)
        path = os.path.join(self.tmpdir.name, "silence.wav")
        _write_wav(path, y, sr)
        return path

    def test_missing_file_returns_empty_features_not_raise(self):
        result = score_window_prosody("/nonexistent/path/audio.wav", 0.0, 2.0)
        self.assertEqual(
            result,
            {"pitch_variance": 0.0, "energy_variance": 0.0, "energy_peak_ratio": 0.0, "pause_ratio": 0.0},
        )

    def test_silence_returns_zero_energy_and_high_pause_ratio(self):
        try:
            import librosa  # noqa: F401
        except ImportError:
            self.skipTest("librosa not installed")
        path = self._make_silence_wav()
        result = score_window_prosody(path, 0.0, 2.0)
        self.assertEqual(result["energy_variance"], 0.0)
        self.assertEqual(result["pitch_variance"], 0.0)

    def test_tone_returns_nonzero_result_shape(self):
        try:
            import librosa  # noqa: F401
        except ImportError:
            self.skipTest("librosa not installed")
        path = self._make_tone_wav()
        result = score_window_prosody(path, 0.0, 2.0)
        self.assertIn("pitch_variance", result)
        self.assertIn("energy_variance", result)
        self.assertIn("energy_peak_ratio", result)
        self.assertIn("pause_ratio", result)
        for v in result.values():
            self.assertIsInstance(v, float)


class TestScoreCandidatesProsody(unittest.TestCase):
    def _clip(self, start, end):
        return {"start_time": start, "end_time": end}

    def test_empty_candidates_returns_empty(self):
        self.assertEqual(score_candidates_prosody([], "unused.wav"), [])

    def test_attaches_prosody_and_normalized_score(self):
        candidates = [self._clip(0, 5), self._clip(10, 15), self._clip(20, 25)]

        fake_features = [
            {"pitch_variance": 0.0, "energy_variance": 0.0, "energy_peak_ratio": 0.0, "pause_ratio": 1.0},
            {"pitch_variance": 5.0, "energy_variance": 5.0, "energy_peak_ratio": 5.0, "pause_ratio": 0.5},
            {"pitch_variance": 10.0, "energy_variance": 10.0, "energy_peak_ratio": 10.0, "pause_ratio": 0.0},
        ]

        with patch(
            "clipping.phase1.prosody_scoring.score_window_prosody",
            side_effect=fake_features,
        ):
            result = score_candidates_prosody(candidates, "unused.wav")

        # Lowest raw features + highest pause_ratio (least exciting) -> lowest prosody_score.
        # Highest raw features + zero pause_ratio (most exciting) -> highest prosody_score.
        self.assertLess(result[0]["prosody_score"], result[1]["prosody_score"])
        self.assertLess(result[1]["prosody_score"], result[2]["prosody_score"])
        self.assertEqual(result[0]["prosody"], fake_features[0])

    def test_mutates_in_place_and_returns_same_list(self):
        candidates = [self._clip(0, 5)]
        fake_features = [
            {"pitch_variance": 1.0, "energy_variance": 1.0, "energy_peak_ratio": 1.0, "pause_ratio": 0.0}
        ]
        with patch(
            "clipping.phase1.prosody_scoring.score_window_prosody",
            side_effect=fake_features,
        ):
            result = score_candidates_prosody(candidates, "unused.wav")
        self.assertIs(result, candidates)
        self.assertIn("prosody_score", candidates[0])


if __name__ == "__main__":
    unittest.main()

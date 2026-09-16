"""
Unit tests for clipping.phase1.visual_scoring

sample_frames() is tested against a small synthetic video file generated
with OpenCV (no network access). score_window_visual()/score_candidates_visual()
are tested with the SigLIP model itself stubbed out (downloading+running a
real vision-language model in unit tests is neither fast nor deterministic
enough) so the aggregation/plumbing logic is what's actually verified here.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from clipping.phase1.visual_scoring import (
    sample_frames,
    score_candidates_visual,
    score_window_visual,
)


def _make_test_video(path, num_frames=60, fps=30, size=(64, 64)):
    import cv2

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, size)
    for i in range(num_frames):
        frame = np.full((size[1], size[0], 3), fill_value=(i * 4) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class TestSampleFrames(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_missing_video_returns_empty_list(self):
        frames = sample_frames("/nonexistent/video.mp4", 0.0, 2.0)
        self.assertEqual(frames, [])

    def test_samples_requested_frame_count_from_real_video(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("cv2 not installed")
        path = os.path.join(self.tmpdir.name, "test.mp4")
        _make_test_video(path, num_frames=60, fps=30)  # 2s video
        frames = sample_frames(path, 0.0, 2.0, num_frames=4)
        self.assertGreater(len(frames), 0)
        self.assertLessEqual(len(frames), 4)
        # Sampled frames are RGB (H, W, 3).
        for f in frames:
            self.assertEqual(f.ndim, 3)
            self.assertEqual(f.shape[2], 3)


class TestScoreWindowVisual(unittest.TestCase):
    def test_no_frames_returns_empty_result_without_loading_model(self):
        with patch(
            "clipping.phase1.visual_scoring.sample_frames", return_value=[]
        ) as mocked_sample, patch(
            "clipping.phase1.visual_scoring._get_siglip_model"
        ) as mocked_model:
            result = score_window_visual("/nonexistent/video.mp4", 0.0, 2.0)
        self.assertEqual(result, {"visual_interest": 0.0, "frames_sampled": 0})
        mocked_sample.assert_called_once()
        mocked_model.assert_not_called()

    def test_model_failure_degrades_to_empty_result(self):
        fake_frame = np.zeros((32, 32, 3), dtype=np.uint8)
        with patch(
            "clipping.phase1.visual_scoring.sample_frames", return_value=[fake_frame]
        ), patch(
            "clipping.phase1.visual_scoring._get_siglip_model",
            side_effect=RuntimeError("model load failed"),
        ):
            result = score_window_visual("fake.mp4", 0.0, 2.0)
        self.assertEqual(result, {"visual_interest": 0.0, "frames_sampled": 0})


class TestScoreCandidatesVisual(unittest.TestCase):
    def _clip(self, start, end):
        return {"start_time": start, "end_time": end}

    def test_empty_candidates_returns_empty(self):
        self.assertEqual(score_candidates_visual([], "unused.mp4"), [])

    def test_attaches_visual_and_score_per_candidate(self):
        candidates = [self._clip(0, 5), self._clip(10, 15)]
        fake_results = [
            {"visual_interest": 0.2, "frames_sampled": 4},
            {"visual_interest": 0.8, "frames_sampled": 4},
        ]
        with patch(
            "clipping.phase1.visual_scoring.score_window_visual",
            side_effect=fake_results,
        ):
            result = score_candidates_visual(candidates, "unused.mp4")

        self.assertEqual(result[0]["visual_score"], 0.2)
        self.assertEqual(result[1]["visual_score"], 0.8)
        self.assertEqual(result[0]["visual"], fake_results[0])

    def test_mutates_in_place_and_returns_same_list(self):
        candidates = [self._clip(0, 5)]
        fake_results = [{"visual_interest": 0.5, "frames_sampled": 2}]
        with patch(
            "clipping.phase1.visual_scoring.score_window_visual",
            side_effect=fake_results,
        ):
            result = score_candidates_visual(candidates, "unused.mp4")
        self.assertIs(result, candidates)
        self.assertIn("visual_score", candidates[0])


if __name__ == "__main__":
    unittest.main()

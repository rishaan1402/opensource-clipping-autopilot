"""
Unit tests for clipping.phase1.checkpoint

Covers:
- Step completion tracking and data round-trip
- Failure marking
- Resume/skip decision logic
- State persistence across manager instances (simulates process restart)
- Reset behavior
"""

import json
import os
import tempfile
import unittest

from clipping.phase1.checkpoint import CheckpointManager, StepValidator


class TestCheckpointManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_new_manager_has_no_complete_steps(self):
        ckpt = CheckpointManager(self.output_dir)
        self.assertFalse(ckpt.is_step_complete("download"))
        self.assertIsNone(ckpt.get_last_complete_step())

    def test_mark_step_complete_persists_data(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_complete("download", {"file": "video.mp4"})

        self.assertTrue(ckpt.is_step_complete("download"))
        data = ckpt.get_step_data("download")
        self.assertEqual(data["file"], "video.mp4")

    def test_mark_step_failed_is_not_complete(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_failed("transcribe", "whisper crashed")

        self.assertFalse(ckpt.is_step_complete("transcribe"))
        self.assertIsNone(ckpt.get_step_data("transcribe"))

    def test_failed_then_retried_to_success_becomes_complete(self):
        """A step that failed and is later retried successfully updates state."""
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_failed("render_clip_1", "ffmpeg error")
        self.assertFalse(ckpt.is_step_complete("render_clip_1"))

        ckpt.mark_step_complete("render_clip_1", {"manifest_entry": {"status": "success"}})
        self.assertTrue(ckpt.is_step_complete("render_clip_1"))

    def test_state_persists_across_manager_instances(self):
        """Simulates a crashed process: new CheckpointManager instance on the
        same outputs_dir must see previously completed steps."""
        ckpt1 = CheckpointManager(self.output_dir)
        ckpt1.mark_step_complete("download", {"file": "video.mp4"})
        ckpt1.mark_step_complete("transcribe", {"full_transcript": "hello", "segment_data": []})

        # Fresh instance — simulates resuming after a crash
        ckpt2 = CheckpointManager(self.output_dir)
        self.assertTrue(ckpt2.is_step_complete("download"))
        self.assertTrue(ckpt2.is_step_complete("transcribe"))
        self.assertEqual(ckpt2.get_step_data("download")["file"], "video.mp4")

    def test_get_progress_reports_all_steps(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_complete("download", {})
        ckpt.mark_step_failed("transcribe", "oom")

        progress = ckpt.get_progress()
        self.assertEqual(progress["download"], "completed")
        self.assertEqual(progress["transcribe"], "failed")

    def test_get_last_complete_step_tracks_order(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_complete("download", {})
        ckpt.mark_step_complete("transcribe", {})
        ckpt.mark_step_complete("ai_analysis", {})

        self.assertEqual(ckpt.get_last_complete_step(), "ai_analysis")

    def test_reset_clears_all_state(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_complete("download", {"file": "video.mp4"})
        ckpt.reset()

        self.assertFalse(ckpt.is_step_complete("download"))
        self.assertEqual(ckpt.get_progress(), {})

    def test_reset_persists_across_instances(self):
        ckpt1 = CheckpointManager(self.output_dir)
        ckpt1.mark_step_complete("download", {"file": "video.mp4"})
        ckpt1.reset()

        ckpt2 = CheckpointManager(self.output_dir)
        self.assertFalse(ckpt2.is_step_complete("download"))

    def test_metadata_storage(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.set_metadata("source_url", "https://youtube.com/watch?v=abc")
        self.assertEqual(ckpt.get_metadata("source_url"), "https://youtube.com/watch?v=abc")
        self.assertEqual(ckpt.get_metadata("missing_key", "default"), "default")

    def test_checkpoint_dir_created(self):
        CheckpointManager(self.output_dir)
        self.assertTrue(os.path.isdir(os.path.join(self.output_dir, ".checkpoints")))

    def test_state_file_is_valid_json(self):
        ckpt = CheckpointManager(self.output_dir)
        ckpt.mark_step_complete("download", {"file": "video.mp4"})

        with open(ckpt.state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("steps", data)
        self.assertIn("download", data["steps"])


class TestStepValidator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_validate_download_missing_file(self):
        self.assertFalse(StepValidator.validate_download(self.output_dir))

    def test_validate_download_present_file(self):
        open(os.path.join(self.output_dir, "source_video.mp4"), "w").close()
        self.assertTrue(StepValidator.validate_download(self.output_dir))

    def test_validate_rendered_clips_none_present(self):
        self.assertFalse(StepValidator.validate_rendered_clips(self.output_dir))

    def test_validate_rendered_clips_with_expected_count(self):
        clips_dir = os.path.join(self.output_dir, "clips")
        os.makedirs(clips_dir)
        open(os.path.join(clips_dir, "a.mp4"), "w").close()
        open(os.path.join(clips_dir, "b.mp4"), "w").close()

        self.assertTrue(StepValidator.validate_rendered_clips(self.output_dir, expected_count=2))
        self.assertFalse(StepValidator.validate_rendered_clips(self.output_dir, expected_count=3))


if __name__ == "__main__":
    unittest.main()

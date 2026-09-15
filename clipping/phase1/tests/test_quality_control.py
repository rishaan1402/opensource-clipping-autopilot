"""
Unit tests for clipping.phase1.quality_control

Covers:
- ClipValidator duration/integrity checks
- CaptionValidator caption text validation
- QualityControlManager batch validation over a directory
- Real video fixtures generated with ffmpeg (not mocks) so duration/audio
  checks exercise the actual ffprobe/ffmpeg code path
"""

import os
import subprocess
import tempfile
import unittest
import shutil

from clipping.phase1.quality_control import ClipValidator, CaptionValidator, QualityControlManager


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_test_clip(path: str, duration: float, silent: bool = False):
    """Generate a tiny real mp4 with ffmpeg (color bars + tone, or silence)."""
    audio_src = "anullsrc=r=44100:cl=stereo" if silent else "sine=frequency=440:sample_rate=44100"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s=320x240:d={duration}",
        "-f", "lavfi", "-i", f"{audio_src}",
        "-t", str(duration), "-c:v", "libx264", "-c:a", "aac",
        "-shortest", path,
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg/ffprobe not available")
class TestClipValidatorWithRealFiles(unittest.TestCase):
    """Integration-style tests against real ffmpeg-generated clips."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_valid_clip_passes(self):
        path = os.path.join(self.tmpdir.name, "clip.mp4")
        _make_test_clip(path, duration=10)

        result = ClipValidator.validate_clip(path)
        self.assertTrue(result["valid"], result["errors"])
        self.assertAlmostEqual(result["metrics"]["duration_seconds"], 10, delta=1)

    def test_too_short_clip_fails(self):
        path = os.path.join(self.tmpdir.name, "clip.mp4")
        _make_test_clip(path, duration=2)

        result = ClipValidator.validate_clip(path)
        self.assertFalse(result["valid"])
        self.assertTrue(any("too short" in e for e in result["errors"]))

    def test_silent_clip_fails(self):
        path = os.path.join(self.tmpdir.name, "clip.mp4")
        _make_test_clip(path, duration=10, silent=True)

        result = ClipValidator.validate_clip(path)
        self.assertFalse(result["valid"])
        self.assertIn("audio_level_db", result["metrics"])

    def test_ffprobe_command_succeeds_on_real_ffmpeg(self):
        """Regression: the ffprobe invocation must actually run successfully
        against the system's real ffprobe build (caught a bad 'noescapes=1'
        sub-option that ffmpeg 9.x's -of default writer rejects outright)."""
        path = os.path.join(self.tmpdir.name, "clip.mp4")
        _make_test_clip(path, duration=7)
        duration = ClipValidator.get_clip_duration(path)
        self.assertIsNotNone(duration, "get_clip_duration must not silently fail on a valid file")
        self.assertAlmostEqual(duration, 7, delta=1)

    def test_nonexistent_file_fails(self):
        result = ClipValidator.validate_clip("/nonexistent/path/clip.mp4")
        self.assertFalse(result["valid"])
        self.assertTrue(len(result["errors"]) > 0)

    def test_long_clip_within_pipeline_bounds_passes(self):
        """Regression: MAX_CLIP_DURATION must accommodate the base pipeline's
        own up-to-179s clips, not just 60s Shorts. Use a synthetic duration
        check (real 170s ffmpeg render is too slow for a unit test) by
        monkeypatching get_clip_duration instead."""
        original = ClipValidator.get_clip_duration
        try:
            ClipValidator.get_clip_duration = staticmethod(lambda path: 170.0)
            path = os.path.join(self.tmpdir.name, "clip.mp4")
            _make_test_clip(path, duration=2)  # content irrelevant, duration is patched
            result = ClipValidator.validate_clip(path)
            self.assertNotIn(
                "Clip too long", " ".join(result["errors"]),
                "170s clip should be within pipeline's 20-179s bounds"
            )
        finally:
            ClipValidator.get_clip_duration = original


class TestClipValidatorPureLogic(unittest.TestCase):
    """Tests that don't need ffmpeg — pure threshold logic via monkeypatching."""

    def test_duration_bounds_constants_cover_pipeline_range(self):
        """clipping.engine allows 20-179s clips; QC must not reject that range."""
        self.assertLessEqual(ClipValidator.MIN_CLIP_DURATION, 20)
        self.assertGreaterEqual(ClipValidator.MAX_CLIP_DURATION, 179)


class TestCaptionValidator(unittest.TestCase):
    def test_valid_caption(self):
        is_valid, issues = CaptionValidator.validate_caption("This is a normal caption line")
        self.assertTrue(is_valid)
        self.assertEqual(issues, [])

    def test_too_short_caption(self):
        is_valid, issues = CaptionValidator.validate_caption("Hi")
        self.assertFalse(is_valid)

    def test_hallucination_keyword_flagged(self):
        is_valid, issues = CaptionValidator.validate_caption("[INAUDIBLE] something something")
        self.assertFalse(is_valid)
        self.assertTrue(any("hallucination" in i.lower() for i in issues))

    def test_validate_srt_parses_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "test.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(
                    "1\n00:00:00,000 --> 00:00:02,000\nHello world this is a caption\n\n"
                    "2\n00:00:02,000 --> 00:00:04,000\nAnother caption line here\n\n"
                )
            result = CaptionValidator.validate_srt(srt_path)
            self.assertEqual(result["total_captions"], 2)
            self.assertEqual(len(result["suspect_captions"]), 0)

    def test_validate_srt_flags_hallucinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "test.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("1\n00:00:00,000 --> 00:00:02,000\n[MUSIC]\n\n")
            result = CaptionValidator.validate_srt(srt_path)
            self.assertEqual(len(result["suspect_captions"]), 1)

    def test_validate_srt_missing_file(self):
        result = CaptionValidator.validate_srt("/nonexistent/file.srt")
        self.assertFalse(result["valid"])


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg/ffprobe not available")
class TestQualityControlManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_validate_all_clips_mixed_directory(self):
        good_path = os.path.join(self.tmpdir.name, "highlight_rank_1_ready.mp4")
        bad_path = os.path.join(self.tmpdir.name, "highlight_rank_2_ready.mp4")
        _make_test_clip(good_path, duration=10)
        _make_test_clip(bad_path, duration=2)  # too short

        qc = QualityControlManager(strict_mode=False)
        summary = qc.validate_all_clips(self.tmpdir.name)

        self.assertEqual(summary["total_clips"], 2)
        self.assertEqual(summary["valid_clips"], 1)
        self.assertEqual(len(summary["invalid_clips"]), 1)

    def test_validate_all_clips_empty_directory(self):
        qc = QualityControlManager()
        summary = qc.validate_all_clips(self.tmpdir.name)
        self.assertEqual(summary["total_clips"], 0)
        self.assertEqual(summary["valid_clips"], 0)

    def test_validate_all_clips_missing_directory(self):
        qc = QualityControlManager()
        summary = qc.validate_all_clips(os.path.join(self.tmpdir.name, "does_not_exist"))
        self.assertEqual(len(summary["invalid_clips"]), 1)

    def test_validate_all_clips_ignores_non_mp4_files(self):
        _make_test_clip(os.path.join(self.tmpdir.name, "clip.mp4"), duration=10)
        with open(os.path.join(self.tmpdir.name, "metadata.json"), "w") as f:
            f.write("{}")

        qc = QualityControlManager()
        summary = qc.validate_all_clips(self.tmpdir.name)
        self.assertEqual(summary["total_clips"], 1)


if __name__ == "__main__":
    unittest.main()

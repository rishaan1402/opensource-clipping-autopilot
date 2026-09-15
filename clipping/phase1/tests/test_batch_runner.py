"""
Unit tests for clipping.phase1.batch_runner

Covers:
- slugify_source uniqueness/safety
- build_item_config isolation (no cross-item / cross-base-cfg collisions)
- run_batch continues past a failing item and records results
- write_batch_report / print_batch_summary sanity

run_pipeline itself is mocked — these tests never touch the network,
Whisper, Gemini, or ffmpeg.
"""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from clipping.phase1.input_handler import InputSource
from clipping.phase1.batch_runner import (
    slugify_source,
    build_item_config,
    run_batch,
    write_batch_report,
)


def _make_base_cfg(outputs_dir: str):
    return SimpleNamespace(
        outputs_dir=outputs_dir,
        file_video_asli=os.path.join(outputs_dir, "video_asli.mp4"),
        url_youtube=None,
        source_platform="youtube",
        font_dir="/shared/fonts",
        base_dir="/project",
    )


class TestSlugifySource(unittest.TestCase):
    def test_uses_title_when_present(self):
        source = InputSource(source="https://youtube.com/watch?v=abc", title="My Cool Video!")
        slug = slugify_source(source, 1)
        self.assertIn("my_cool_video", slug)
        self.assertTrue(slug.startswith("001_"))

    def test_falls_back_to_url_when_no_title(self):
        source = InputSource(source="https://youtube.com/watch?v=abc123")
        slug = slugify_source(source, 2)
        self.assertTrue(slug.startswith("002_"))

    def test_index_guarantees_uniqueness_for_identical_titles(self):
        source_a = InputSource(source="https://youtube.com/watch?v=a", title="Same Title")
        source_b = InputSource(source="https://youtube.com/watch?v=b", title="Same Title")
        self.assertNotEqual(slugify_source(source_a, 1), slugify_source(source_b, 2))

    def test_slug_is_filesystem_safe(self):
        source = InputSource(source="https://youtube.com/watch?v=abc", title="Weird/Chars:*?\"<>|Title")
        slug = slugify_source(source, 1)
        for bad_char in '/:*?"<>|':
            self.assertNotIn(bad_char, slug)


class TestBuildItemConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_cfg = _make_base_cfg(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_isolates_outputs_dir_per_item(self):
        source1 = InputSource(source="https://youtube.com/watch?v=a", title="Video A")
        source2 = InputSource(source="https://youtube.com/watch?v=b", title="Video B")

        cfg1 = build_item_config(self.base_cfg, source1, 1)
        cfg2 = build_item_config(self.base_cfg, source2, 2)

        self.assertNotEqual(cfg1.outputs_dir, cfg2.outputs_dir)
        self.assertNotEqual(cfg1.file_video_asli, cfg2.file_video_asli)

    def test_does_not_mutate_base_cfg(self):
        source = InputSource(source="https://youtube.com/watch?v=a", title="Video A")
        original_outputs_dir = self.base_cfg.outputs_dir

        build_item_config(self.base_cfg, source, 1)

        self.assertEqual(self.base_cfg.outputs_dir, original_outputs_dir)
        self.assertIsNone(self.base_cfg.url_youtube)

    def test_item_dir_created_on_disk(self):
        source = InputSource(source="https://youtube.com/watch?v=a", title="Video A")
        cfg = build_item_config(self.base_cfg, source, 1)
        self.assertTrue(os.path.isdir(cfg.outputs_dir))

    def test_shared_resources_preserved(self):
        """Fonts/base_dir are intentionally shared across batch items."""
        source = InputSource(source="https://youtube.com/watch?v=a", title="Video A")
        cfg = build_item_config(self.base_cfg, source, 1)
        self.assertEqual(cfg.font_dir, self.base_cfg.font_dir)
        self.assertEqual(cfg.base_dir, self.base_cfg.base_dir)

    def test_url_youtube_set_per_item(self):
        source = InputSource(source="https://youtube.com/watch?v=xyz", title="Video")
        cfg = build_item_config(self.base_cfg, source, 1)
        self.assertEqual(cfg.url_youtube, "https://youtube.com/watch?v=xyz")

    def test_local_file_source_points_directly_at_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            source = InputSource(source=f.name)
            cfg = build_item_config(self.base_cfg, source, 1)
            self.assertEqual(cfg.file_video_asli, os.path.abspath(f.name))

    def test_local_file_source_preseeds_download_checkpoint(self):
        """Local files have nothing to download — the per-item checkpoint
        must already mark 'download' complete so run_pipeline's Step 1
        skip-check bypasses engine.download_video (which can't handle a
        local file path as its 'url' argument)."""
        from clipping.phase1.checkpoint import CheckpointManager

        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            source = InputSource(source=f.name)
            self.base_cfg.enable_checkpoint = True
            cfg = build_item_config(self.base_cfg, source, 1)

            checkpoint = CheckpointManager(cfg.outputs_dir)
            self.assertTrue(checkpoint.is_step_complete("download"))
            self.assertEqual(checkpoint.get_step_data("download")["file"], cfg.file_video_asli)

    def test_local_file_checkpoint_not_seeded_when_checkpoint_disabled(self):
        from clipping.phase1.checkpoint import CheckpointManager

        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            source = InputSource(source=f.name)
            self.base_cfg.enable_checkpoint = False
            cfg = build_item_config(self.base_cfg, source, 1)

            checkpoint = CheckpointManager(cfg.outputs_dir)
            self.assertFalse(checkpoint.is_step_complete("download"))


class TestRunBatch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_cfg = _make_base_cfg(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_all_succeed(self):
        sources = [
            InputSource(source="https://youtube.com/watch?v=a", title="A"),
            InputSource(source="https://youtube.com/watch?v=b", title="B"),
        ]
        with patch("clipping.runner.run_pipeline", return_value=[{"rank": 1}, {"rank": 2}]):
            results = run_batch(self.base_cfg, sources)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "success" for r in results))
        self.assertEqual(results[0]["clips_rendered"], 2)

    def test_one_failure_does_not_abort_batch(self):
        sources = [
            InputSource(source="https://youtube.com/watch?v=a", title="A"),
            InputSource(source="https://youtube.com/watch?v=b", title="B"),
            InputSource(source="https://youtube.com/watch?v=c", title="C"),
        ]

        def fake_run_pipeline(cfg):
            if cfg.url_youtube.endswith("=b"):
                raise RuntimeError("simulated download failure")
            return [{"rank": 1}]

        with patch("clipping.runner.run_pipeline", side_effect=fake_run_pipeline):
            results = run_batch(self.base_cfg, sources)

        self.assertEqual(len(results), 3)
        statuses = [r["status"] for r in results]
        self.assertEqual(statuses, ["success", "failed", "success"])
        self.assertIn("simulated download failure", results[1]["error"])

    def test_each_result_has_isolated_outputs_dir(self):
        sources = [
            InputSource(source="https://youtube.com/watch?v=a", title="A"),
            InputSource(source="https://youtube.com/watch?v=b", title="B"),
        ]
        with patch("clipping.runner.run_pipeline", return_value=[]):
            results = run_batch(self.base_cfg, sources)

        self.assertNotEqual(results[0]["outputs_dir"], results[1]["outputs_dir"])


class TestWriteBatchReport(unittest.TestCase):
    def test_roundtrip(self):
        results = [{"source": "https://youtube.com/watch?v=a", "status": "success", "clips_rendered": 3}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "batch_report.json")
            write_batch_report(results, path)

            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, results)


if __name__ == "__main__":
    unittest.main()

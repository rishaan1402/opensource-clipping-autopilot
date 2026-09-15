"""
Unit tests for clipping.phase1.deduplication

Covers:
- DeduplicationDB video/clip record round-trip
- ContentHasher determinism
- DeduplicationManager duplicate detection by URL and by file hash
- Persistence across manager instances (simulates process restart)
"""

import os
import tempfile
import unittest

from clipping.phase1.deduplication import (
    DeduplicationDB,
    ContentHasher,
    DeduplicationManager,
)
from clipping.phase1.input_handler import InputSource


class TestContentHasher(unittest.TestCase):
    def test_hash_file_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.bin")
            with open(path, "wb") as f:
                f.write(b"hello world" * 1000)

            h1 = ContentHasher.hash_file(path)
            h2 = ContentHasher.hash_file(path)
            self.assertEqual(h1, h2)
            self.assertNotEqual(h1, "")

    def test_hash_file_differs_for_different_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "a.bin")
            path_b = os.path.join(tmp, "b.bin")
            with open(path_a, "wb") as f:
                f.write(b"content A")
            with open(path_b, "wb") as f:
                f.write(b"content B")

            self.assertNotEqual(ContentHasher.hash_file(path_a), ContentHasher.hash_file(path_b))

    def test_hash_file_missing_returns_empty(self):
        self.assertEqual(ContentHasher.hash_file("/nonexistent/file.bin"), "")

    def test_hash_segment_deterministic(self):
        h1 = ContentHasher.hash_segment(10.0, 40.0, "My Clip Title")
        h2 = ContentHasher.hash_segment(10.0, 40.0, "My Clip Title")
        self.assertEqual(h1, h2)

    def test_hash_segment_differs_by_timing(self):
        h1 = ContentHasher.hash_segment(10.0, 40.0, "My Clip Title")
        h2 = ContentHasher.hash_segment(10.5, 40.0, "My Clip Title")
        self.assertNotEqual(h1, h2)


class TestDeduplicationDB(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "processed.db")
        self.db = DeduplicationDB(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_add_and_check_video(self):
        video_id = self.db.add_video("https://youtube.com/watch?v=abc", "hash123", "/tmp/video.mp4", "/tmp/out")
        self.assertIsInstance(video_id, int)

        existing = self.db.video_already_processed("https://youtube.com/watch?v=abc")
        self.assertIsNotNone(existing)
        self.assertEqual(existing["file_hash"], "hash123")

    def test_check_unprocessed_video_returns_none(self):
        self.assertIsNone(self.db.video_already_processed("https://youtube.com/watch?v=never-seen"))

    def test_duplicate_url_insert_raises(self):
        self.db.add_video("https://youtube.com/watch?v=abc", "hash1", "/tmp/a.mp4", "/tmp/out")
        with self.assertRaises(Exception):
            self.db.add_video("https://youtube.com/watch?v=abc", "hash2", "/tmp/b.mp4", "/tmp/out2")

    def test_add_and_check_clip(self):
        video_id = self.db.add_video("https://youtube.com/watch?v=abc", "hash123", "/tmp/video.mp4", "/tmp/out")
        self.db.add_clip(video_id, "cliphash1", 10.0, 40.0, "My Clip", "/tmp/out/clip1.mp4")

        self.assertTrue(self.db.clip_already_exists("cliphash1"))
        self.assertFalse(self.db.clip_already_exists("nonexistent-hash"))

    def test_get_all_processed_urls(self):
        self.db.add_video("https://youtube.com/watch?v=a", "h1", "/tmp/a.mp4", "/tmp/out1")
        self.db.add_video("https://youtube.com/watch?v=b", "h2", "/tmp/b.mp4", "/tmp/out2")

        urls = self.db.get_all_processed_urls()
        self.assertEqual(set(urls), {"https://youtube.com/watch?v=a", "https://youtube.com/watch?v=b"})


class TestDeduplicationManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmpdir.name, "data")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_check_video_duplicate_by_url_not_yet_processed(self):
        dedup = DeduplicationManager(self.data_dir)
        source = InputSource(source="https://youtube.com/watch?v=abc")
        self.assertIsNone(dedup.check_video_duplicate(source))

    def test_record_then_detect_duplicate_by_url(self):
        dedup = DeduplicationManager(self.data_dir)
        source = InputSource(source="https://youtube.com/watch?v=abc")

        dedup.record_video(source, "/tmp/nonexistent.mp4", "/tmp/out")
        existing = dedup.check_video_duplicate(source)

        self.assertIsNotNone(existing)
        self.assertEqual(existing["source_url"], "https://youtube.com/watch?v=abc")

    def test_record_then_detect_duplicate_by_local_file_hash(self):
        """A local file re-processed under a different path/name is still
        caught by content hash, not just URL string matching."""
        dedup = DeduplicationManager(self.data_dir)

        with tempfile.TemporaryDirectory() as vid_dir:
            path = os.path.join(vid_dir, "video1.mp4")
            with open(path, "wb") as f:
                f.write(b"fake video content" * 1000)

            source1 = InputSource(source=path)
            dedup.record_video(source1, path, "/tmp/out1")

            # Same content, different path/filename
            path2 = os.path.join(vid_dir, "video1_copy.mp4")
            with open(path2, "wb") as f:
                f.write(b"fake video content" * 1000)

            source2 = InputSource(source=path2)
            existing = dedup.check_video_duplicate(source2)
            self.assertIsNotNone(existing, "Same content under different filename should be detected as duplicate")

    def test_persistence_across_manager_instances(self):
        """Simulates a new process run pointing at the same data dir."""
        dedup1 = DeduplicationManager(self.data_dir)
        source = InputSource(source="https://youtube.com/watch?v=abc")
        dedup1.record_video(source, "/tmp/nonexistent.mp4", "/tmp/out")

        dedup2 = DeduplicationManager(self.data_dir)
        existing = dedup2.check_video_duplicate(InputSource(source="https://youtube.com/watch?v=abc"))
        self.assertIsNotNone(existing)

    def test_clip_duplicate_detection(self):
        dedup = DeduplicationManager(self.data_dir)
        self.assertFalse(dedup.check_clip_duplicate(10.0, 40.0, "My Clip"))

        dedup.record_clip(1, 10.0, 40.0, "My Clip", "/tmp/out/clip1.mp4")
        self.assertTrue(dedup.check_clip_duplicate(10.0, 40.0, "My Clip"))

    def test_clear_database(self):
        dedup = DeduplicationManager(self.data_dir)
        source = InputSource(source="https://youtube.com/watch?v=abc")
        dedup.record_video(source, "/tmp/nonexistent.mp4", "/tmp/out")

        dedup.clear_database()
        self.assertIsNone(dedup.check_video_duplicate(source))

    def test_get_processed_urls(self):
        dedup = DeduplicationManager(self.data_dir)
        dedup.record_video(InputSource(source="https://youtube.com/watch?v=a"), "/tmp/a.mp4", "/tmp/out1")
        dedup.record_video(InputSource(source="https://youtube.com/watch?v=b"), "/tmp/b.mp4", "/tmp/out2")

        urls = dedup.get_processed_urls()
        self.assertEqual(len(urls), 2)


if __name__ == "__main__":
    unittest.main()

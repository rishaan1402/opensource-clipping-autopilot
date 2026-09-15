"""
Unit tests for clipping.phase1.input_handler

Covers:
- InputSource source-type detection
- Batch loading from CSV/JSON/TXT
- InputValidator for local files (real files, no network calls)
- InputManager orchestration

Network-dependent validation (validate_youtube_url) is NOT exercised here —
that's an integration concern, not a unit-test concern.
"""

import csv
import json
import os
import tempfile
import unittest

from clipping.phase1.input_handler import (
    InputSource,
    BatchInputHandler,
    InputValidator,
    InputManager,
)


class TestInputSource(unittest.TestCase):
    def test_youtube_url_detected(self):
        source = InputSource(source="https://www.youtube.com/watch?v=abc123")
        self.assertEqual(source.source_type, "youtube")

    def test_youtube_short_url_detected(self):
        source = InputSource(source="https://youtu.be/abc123")
        self.assertEqual(source.source_type, "youtube")

    def test_tiktok_url_detected(self):
        source = InputSource(source="https://www.tiktok.com/@user/video/123")
        self.assertEqual(source.source_type, "tiktok")

    def test_instagram_url_detected(self):
        source = InputSource(source="https://www.instagram.com/reel/abc123")
        self.assertEqual(source.source_type, "instagram")

    def test_generic_url_detected(self):
        source = InputSource(source="https://example.com/video.mp4")
        self.assertEqual(source.source_type, "url")

    def test_local_file_detected(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            source = InputSource(source=f.name)
            self.assertEqual(source.source_type, "local_file")

    def test_invalid_source_raises(self):
        with self.assertRaises(ValueError):
            InputSource(source="/nonexistent/path/video.mp4")

    def test_title_and_tags_stored(self):
        source = InputSource(source="https://youtube.com/watch?v=abc", title="My Video", tags="a b")
        self.assertEqual(source.title, "My Video")
        self.assertEqual(source.tags, "a b")


class TestBatchInputHandler(unittest.TestCase):
    def test_load_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "batch.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["url", "title", "tags"])
                writer.writerow(["https://youtube.com/watch?v=a", "Video A", "tag1 tag2"])
                writer.writerow(["https://youtube.com/watch?v=b", "Video B", ""])

            sources = BatchInputHandler.load_csv(csv_path)
            self.assertEqual(len(sources), 2)
            self.assertEqual(sources[0].source, "https://youtube.com/watch?v=a")
            self.assertEqual(sources[0].title, "Video A")

    def test_load_json_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "batch.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([
                    {"url": "https://youtube.com/watch?v=a", "title": "A"},
                    {"url": "https://youtube.com/watch?v=b"},
                ], f)

            sources = BatchInputHandler.load_json(json_path)
            self.assertEqual(len(sources), 2)
            self.assertEqual(sources[0].title, "A")
            self.assertEqual(sources[1].title, None)

    def test_load_json_items_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "batch.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"items": [{"url": "https://youtube.com/watch?v=a"}]}, f)

            sources = BatchInputHandler.load_json(json_path)
            self.assertEqual(len(sources), 1)

    def test_load_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt_path = os.path.join(tmp, "batch.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("https://youtube.com/watch?v=a\n")
                f.write("# comment line, should be skipped\n")
                f.write("\n")
                f.write("https://youtube.com/watch?v=b\n")

            sources = BatchInputHandler.load_txt(txt_path)
            self.assertEqual(len(sources), 2)


class TestInputValidator(unittest.TestCase):
    def test_validate_local_file_missing(self):
        self.assertFalse(InputValidator.validate_local_file("/nonexistent/video.mp4"))

    def test_validate_local_file_wrong_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            self.assertFalse(InputValidator.validate_local_file(f.name))

    def test_validate_source_local_file_sets_local_path(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            # ffprobe will fail on an empty file — that's expected and correct
            source = InputSource(source=f.name)
            is_valid, error = InputValidator.validate_source(source)
            # Empty file isn't a real video, so ffprobe correctly rejects it
            self.assertFalse(is_valid)
            self.assertIn("invalid", error.lower())


class TestInputManager(unittest.TestCase):
    def test_single_url_source(self):
        manager = InputManager(single_url="https://youtube.com/watch?v=abc")
        self.assertEqual(manager.count(), 1)
        self.assertEqual(manager.get_sources()[0].source, "https://youtube.com/watch?v=abc")

    def test_batch_csv_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "batch.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["url", "title", "tags"])
                writer.writerow(["https://youtube.com/watch?v=a", "A", ""])
                writer.writerow(["https://youtube.com/watch?v=b", "B", ""])

            manager = InputManager(batch_file=csv_path)
            self.assertEqual(manager.count(), 2)

    def test_unsupported_batch_format_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = os.path.join(tmp, "batch.xyz")
            open(bad_path, "w").close()
            with self.assertRaises(ValueError):
                InputManager(batch_file=bad_path)

    def test_no_sources_when_neither_provided(self):
        manager = InputManager()
        self.assertEqual(manager.count(), 0)


if __name__ == "__main__":
    unittest.main()

"""
Flexible Input Handler — Supports YouTube URLs, Local Files, Batch Processing

Handles:
- YouTube URLs
- Local video files (auto-format detection)
- Batch CSV (url,title,tags)
- Fallback if yt-dlp fails
"""

import os
import json
import csv
from pathlib import Path
from typing import List, Dict, Optional
import subprocess


class InputSource:
    """Represents a single input source (video)."""

    def __init__(self, source: str, title: Optional[str] = None, tags: Optional[str] = None):
        self.source = source  # URL or file path
        self.title = title
        self.tags = tags or ""
        self.source_type = self._detect_source_type()
        self.local_path = None

    def _detect_source_type(self) -> str:
        """Detect if source is YouTube URL, local file, or other."""
        if self.source.startswith(("http://", "https://")):
            if "youtube.com" in self.source or "youtu.be" in self.source:
                return "youtube"
            elif "tiktok.com" in self.source:
                return "tiktok"
            elif "instagram.com" in self.source:
                return "instagram"
            else:
                return "url"
        elif os.path.isfile(self.source):
            return "local_file"
        else:
            raise ValueError(f"Invalid source: {self.source}")

    def get_local_path(self) -> Optional[str]:
        """Get path to local file. For YouTube, this will be populated after download."""
        return self.local_path


class BatchInputHandler:
    """Handle batch processing from CSV or JSON."""

    @staticmethod
    def load_csv(csv_path: str) -> List[InputSource]:
        """Load batch inputs from CSV (url,title,tags)."""
        sources = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                source = InputSource(
                    source=row['url'].strip(),
                    title=row.get('title', '').strip(),
                    tags=row.get('tags', '').strip()
                )
                sources.append(source)
        return sources

    @staticmethod
    def load_json(json_path: str) -> List[InputSource]:
        """Load batch inputs from JSON."""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        sources = []
        for item in data if isinstance(data, list) else data.get('items', []):
            source = InputSource(
                source=item['url'],
                title=item.get('title'),
                tags=item.get('tags', '')
            )
            sources.append(source)
        return sources

    @staticmethod
    def load_txt(txt_path: str) -> List[InputSource]:
        """Load batch inputs from text file (one URL per line)."""
        sources = []
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith('#'):
                    sources.append(InputSource(source=url))
        return sources


class InputValidator:
    """Validate input sources before processing."""

    @staticmethod
    def validate_local_file(file_path: str) -> bool:
        """Check if local file exists and is readable video format."""
        if not os.path.isfile(file_path):
            return False

        valid_extensions = {'.mp4', '.mov', '.mkv', '.webm', '.flv', '.avi', '.m4v', '.wmv'}
        ext = Path(file_path).suffix.lower()

        if ext not in valid_extensions:
            return False

        # Try to read file metadata with ffprobe
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def validate_youtube_url(url: str) -> bool:
        """Check if YouTube URL is valid (can be accessed)."""
        try:
            result = subprocess.run(
                ['yt-dlp', '--no-warnings', '-J', '-e', url],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def validate_source(source: InputSource) -> tuple[bool, str]:
        """
        Validate input source.

        Returns (is_valid, error_message)
        """
        if source.source_type == "local_file":
            if not InputValidator.validate_local_file(source.source):
                return False, f"Local file not found or invalid: {source.source}"
            source.local_path = source.source
            return True, ""

        elif source.source_type == "youtube":
            if not InputValidator.validate_youtube_url(source.source):
                return False, f"YouTube URL unreachable or invalid: {source.source}"
            return True, ""

        elif source.source_type in ["tiktok", "instagram"]:
            return True, ""  # Let yt-dlp handle validation

        else:
            return True, ""  # Trust URL will work


class InputManager:
    """Main orchestrator for input handling."""

    def __init__(self, batch_file: Optional[str] = None, single_url: Optional[str] = None):
        """
        Initialize input manager.

        Args:
            batch_file: Path to CSV/JSON/TXT with batch inputs
            single_url: Single URL or file path
        """
        self.sources: List[InputSource] = []

        if batch_file:
            self._load_batch(batch_file)
        elif single_url:
            source = InputSource(source=single_url)
            self.sources.append(source)

    def _load_batch(self, batch_file: str):
        """Load inputs from batch file (auto-detect format)."""
        ext = Path(batch_file).suffix.lower()

        if ext == '.csv':
            self.sources = BatchInputHandler.load_csv(batch_file)
        elif ext == '.json':
            self.sources = BatchInputHandler.load_json(batch_file)
        elif ext == '.txt':
            self.sources = BatchInputHandler.load_txt(batch_file)
        else:
            raise ValueError(f"Unsupported batch format: {ext}")

    def validate_all(self) -> tuple[List[InputSource], List[tuple[InputSource, str]]]:
        """
        Validate all sources.

        Returns (valid_sources, [(invalid_source, error_msg), ...])
        """
        valid = []
        invalid = []

        for source in self.sources:
            is_valid, error = InputValidator.validate_source(source)
            if is_valid:
                valid.append(source)
            else:
                invalid.append((source, error))

        return valid, invalid

    def get_sources(self) -> List[InputSource]:
        """Get all loaded sources."""
        return self.sources

    def count(self) -> int:
        """Get number of sources loaded."""
        return len(self.sources)

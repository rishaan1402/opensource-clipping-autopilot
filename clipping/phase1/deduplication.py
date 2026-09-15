"""
Deduplication Manager

Tracks processed videos and clips to prevent re-processing.
Uses content hashing to detect duplicates.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, List
import sqlite3

from .input_handler import InputSource


class DeduplicationDB:
    """SQLite database for tracking processed content."""

    def __init__(self, db_path: str):
        """Initialize deduplication database."""
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS processed_videos (
                    id INTEGER PRIMARY KEY,
                    source_url TEXT UNIQUE,
                    file_hash TEXT,
                    local_path TEXT,
                    processed_date TEXT,
                    output_dir TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER,
                    clip_hash TEXT UNIQUE,
                    start_time REAL,
                    end_time REAL,
                    title TEXT,
                    output_path TEXT,
                    created_date TEXT,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id)
                )
            ''')
            conn.commit()

    def add_video(self, source_url: str, file_hash: str, local_path: str, output_dir: str) -> int:
        """Record a processed video."""
        from datetime import datetime

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO processed_videos (source_url, file_hash, local_path, processed_date, output_dir)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(source_url) DO UPDATE SET
                       file_hash=excluded.file_hash,
                       local_path=excluded.local_path,
                       processed_date=excluded.processed_date,
                       output_dir=excluded.output_dir''',
                (source_url, file_hash, local_path, datetime.now().isoformat(), output_dir)
            )
            conn.commit()
            if cursor.lastrowid:
                return cursor.lastrowid
            cursor.execute('SELECT id FROM processed_videos WHERE source_url = ?', (source_url,))
            return cursor.fetchone()[0]

    def video_already_processed(self, source_url: str) -> Optional[Dict]:
        """Check if a video was already processed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM processed_videos WHERE source_url = ?', (source_url,))
            row = cursor.fetchone()

            if row:
                return {
                    'id': row[0],
                    'source_url': row[1],
                    'file_hash': row[2],
                    'local_path': row[3],
                    'processed_date': row[4],
                    'output_dir': row[5]
                }
        return None

    def add_clip(self, video_id: int, clip_hash: str, start_time: float, end_time: float, title: str, output_path: str):
        """Record a generated clip."""
        from datetime import datetime

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO clips (video_id, clip_hash, start_time, end_time, title, output_path, created_date) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (video_id, clip_hash, start_time, end_time, title, output_path, datetime.now().isoformat())
            )
            conn.commit()

    def clip_already_exists(self, clip_hash: str) -> bool:
        """Check if a clip with same hash was already generated."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM clips WHERE clip_hash = ?', (clip_hash,))
            return cursor.fetchone() is not None

    def get_all_processed_urls(self) -> List[str]:
        """Get list of all processed video URLs."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT source_url FROM processed_videos')
            return [row[0] for row in cursor.fetchall()]


class ContentHasher:
    """Generate content hashes for deduplication."""

    @staticmethod
    def hash_file(file_path: str, chunk_size: int = 8192, max_bytes: int = 100 * 1024 * 1024) -> str:
        """
        Hash file content (using first 100MB for large files).

        Args:
            file_path: Path to file to hash
            chunk_size: Size of chunks to read
            max_bytes: Maximum bytes to hash (for performance on large videos)

        Returns:
            Hex hash string
        """
        hasher = hashlib.md5()
        bytes_read = 0

        try:
            with open(file_path, 'rb') as f:
                while bytes_read < max_bytes:
                    chunk = f.read(min(chunk_size, max_bytes - bytes_read))
                    if not chunk:
                        break
                    hasher.update(chunk)
                    bytes_read += len(chunk)
        except IOError:
            return ""

        return hasher.hexdigest()

    @staticmethod
    def hash_segment(start: float, end: float, title: str) -> str:
        """Hash a video segment for duplicate detection."""
        content = f"{start:.2f}_{end:.2f}_{title}".encode('utf-8')
        return hashlib.md5(content).hexdigest()


class DeduplicationManager:
    """Main orchestrator for deduplication."""

    def __init__(self, data_dir: str):
        """Initialize deduplication manager."""
        self.data_dir = data_dir
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db_path = os.path.join(data_dir, 'processed.db')
        self.db = DeduplicationDB(self.db_path)

    def check_video_duplicate(self, source: InputSource) -> Optional[Dict]:
        """
        Check if video was already processed.

        Returns None if not processed, or dict with previous processing info.
        """
        # Check by URL first
        existing = self.db.video_already_processed(source.source)
        if existing:
            return existing

        # For local files, also check by content hash
        if source.source_type == 'local_file':
            file_hash = ContentHasher.hash_file(source.source)
            if file_hash:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM processed_videos WHERE file_hash = ?', (file_hash,))
                    row = cursor.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'source_url': row[1],
                            'file_hash': row[2],
                            'local_path': row[3],
                            'processed_date': row[4],
                            'output_dir': row[5]
                        }

        return None

    def record_video(self, source: InputSource, local_path: str, output_dir: str):
        """Record that a video was processed."""
        file_hash = ContentHasher.hash_file(local_path) if os.path.isfile(local_path) else ""
        self.db.add_video(source.source, file_hash, local_path, output_dir)

    def check_clip_duplicate(self, start: float, end: float, title: str) -> bool:
        """Check if this exact clip was already generated."""
        clip_hash = ContentHasher.hash_segment(start, end, title)
        return self.db.clip_already_exists(clip_hash)

    def record_clip(self, video_id: int, start: float, end: float, title: str, output_path: str):
        """Record that a clip was generated."""
        clip_hash = ContentHasher.hash_segment(start, end, title)
        self.db.add_clip(video_id, clip_hash, start, end, title, output_path)

    def get_processed_urls(self) -> List[str]:
        """Get all processed URLs."""
        return self.db.get_all_processed_urls()

    def clear_database(self):
        """Clear all deduplication records."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = DeduplicationDB(self.db_path)

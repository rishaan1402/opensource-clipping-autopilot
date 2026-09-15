"""
Checkpoint & Resume Manager

Saves progress at each pipeline step so we can resume from any point.
Tracks:
- Download status
- Transcription completion
- AI analysis results
- Clip metadata
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages pipeline checkpoints for recovery."""

    def __init__(self, output_dir: str, source_key: Optional[str] = None):
        """
        Initialize checkpoint manager.

        Args:
            output_dir: Directory where checkpoints will be stored
            source_key: Identifier for the current source (e.g. the video
                URL/path being processed). If the loaded checkpoint file was
                written for a different source_key, all cached steps are
                discarded — otherwise a stale transcript/analysis from a
                previous, unrelated video would silently get reused (e.g.
                via --skip-download), producing subtitles/clips for the
                wrong video entirely.
        """
        self.output_dir = output_dir
        self.checkpoint_dir = os.path.join(output_dir, '.checkpoints')
        self.state_file = os.path.join(self.checkpoint_dir, 'pipeline_state.json')
        self.source_key = source_key

        Path(self.checkpoint_dir).mkdir(parents=True, exist_ok=True)
        self._init_state()

        if source_key is not None and self.state.get('source_key') != source_key:
            # Mismatch includes the "legacy checkpoint with no source_key at
            # all" case (self.state.get('source_key') is None) — an untagged
            # checkpoint predates this guard and cannot be trusted to belong
            # to the current source, so it must be invalidated too rather
            # than silently adopted.
            old_key = self.state.get('source_key')
            had_steps = bool(self.state.get('steps'))
            if had_steps:
                logger.warning(
                    f"Checkpoint source changed ({old_key!r} -> {source_key!r}); "
                    f"discarding stale checkpoint state."
                )
                print(
                    f"⚠️  Sumber video berbeda dari checkpoint sebelumnya "
                    f"({old_key!r} -> {source_key!r}). "
                    f"Checkpoint lama dihapus untuk mencegah transkrip/klip yang salah."
                )
            self.state = {
                'created_at': datetime.now().isoformat(),
                'steps': {},
                'metadata': {},
                'source_key': source_key,
            }
            self.save_state()

    def _init_state(self):
        """Load existing state file, or initialize a fresh one if none exists."""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.state = json.load(f)
        else:
            self.state = {
                'created_at': datetime.now().isoformat(),
                'steps': {},
                'metadata': {}
            }
            self.save_state()

    def save_state(self):
        """Save current state to file."""
        self.state['updated_at'] = datetime.now().isoformat()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
        logger.debug(f"State saved: {self.state_file}")

    def load_state(self) -> Dict:
        """Load state from file."""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.state = json.load(f)
            return self.state
        return None

    def mark_step_complete(self, step_name: str, data: Optional[Dict] = None):
        """
        Mark a pipeline step as complete.

        Args:
            step_name: Name of the step (e.g., 'download', 'transcribe', 'analyze')
            data: Optional data to store with checkpoint
        """
        self.state['steps'][step_name] = {
            'status': 'completed',
            'timestamp': datetime.now().isoformat(),
            'data': data or {}
        }
        self.save_state()
        logger.info(f"✓ Step '{step_name}' marked complete")

    def mark_step_failed(self, step_name: str, error: str):
        """Mark a pipeline step as failed."""
        self.state['steps'][step_name] = {
            'status': 'failed',
            'timestamp': datetime.now().isoformat(),
            'error': error
        }
        self.save_state()
        logger.error(f"✗ Step '{step_name}' failed: {error}")

    def is_step_complete(self, step_name: str) -> bool:
        """Check if a step is already complete."""
        return self.state['steps'].get(step_name, {}).get('status') == 'completed'

    def get_step_data(self, step_name: str) -> Optional[Dict]:
        """Get data from a completed step."""
        step = self.state['steps'].get(step_name, {})
        if step.get('status') == 'completed':
            return step.get('data', {})
        return None

    def get_last_complete_step(self) -> Optional[str]:
        """Get the name of the last completed step."""
        completed_steps = [
            name for name, step in self.state['steps'].items()
            if step.get('status') == 'completed'
        ]
        if completed_steps:
            return completed_steps[-1]
        return None

    def get_progress(self) -> Dict[str, str]:
        """Get progress summary."""
        progress = {}
        for step_name, step_data in self.state['steps'].items():
            progress[step_name] = step_data.get('status', 'unknown')
        return progress

    def set_metadata(self, key: str, value: Any):
        """Store metadata."""
        self.state['metadata'][key] = value
        self.save_state()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata."""
        return self.state['metadata'].get(key, default)

    def reset(self):
        """Reset all checkpoints (start fresh)."""
        self.state = {
            'created_at': datetime.now().isoformat(),
            'steps': {},
            'metadata': {}
        }
        self.save_state()
        logger.info("Pipeline state reset")


class StepValidator:
    """Validates that output files from each step exist."""

    @staticmethod
    def validate_download(output_dir: str) -> bool:
        """Check if video was downloaded."""
        video_path = os.path.join(output_dir, 'video_asli.mp4')
        return os.path.isfile(video_path)

    @staticmethod
    def validate_transcription(output_dir: str) -> bool:
        """Check if transcription was completed."""
        srt_path = os.path.join(output_dir, 'transcript.srt')
        json_path = os.path.join(output_dir, 'transcript.json')
        return os.path.isfile(srt_path) or os.path.isfile(json_path)

    @staticmethod
    def validate_ai_analysis(output_dir: str) -> bool:
        """Check if AI analysis was completed."""
        json_path = os.path.join(output_dir, 'gemini_response.json')
        return os.path.isfile(json_path)

    @staticmethod
    def validate_clips_metadata(output_dir: str) -> bool:
        """Check if clips metadata exists."""
        json_path = os.path.join(output_dir, 'metadata_preview.json')
        return os.path.isfile(json_path)

    @staticmethod
    def validate_rendered_clips(output_dir: str, expected_count: int = None) -> bool:
        """Check if clips were rendered."""
        clips_dir = os.path.join(output_dir, 'clips')
        if not os.path.isdir(clips_dir):
            return False

        mp4_files = list(Path(clips_dir).glob('*.mp4'))
        if expected_count:
            return len(mp4_files) >= expected_count
        return len(mp4_files) > 0

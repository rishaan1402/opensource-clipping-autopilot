"""
Quality Control & Validation

Validates output quality before publishing.
Checks:
- Clip length (min/max)
- Audio levels (not silent)
- File integrity
- Caption quality
"""

import os
import subprocess
import json
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class ClipValidator:
    """Validates generated clips."""

    # Configuration
    # Aligned with clipping.engine.MIN_CLIP_DURATION / MAX_CLIP_DURATION (20-179s),
    # plus margin for hook/intro segments the renderer prepends on top of the
    # core clip window. Not a hardcoded Shorts-only (60s) limit — this pipeline
    # supports longer "highlight" clips too.
    MIN_CLIP_DURATION = 5  # seconds
    MAX_CLIP_DURATION = 200  # seconds
    MIN_AUDIO_LEVEL = -60  # dB (warn if too quiet)
    MIN_AUDIO_DURATION = 1  # seconds

    @staticmethod
    def get_clip_duration(file_path: str) -> Optional[float]:
        """Get duration of a video file in seconds."""
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Failed to get duration: {e}")
        return None

    @staticmethod
    def get_audio_level(file_path: str) -> Optional[float]:
        """Get peak audio level in dB."""
        try:
            result = subprocess.run(
                ['ffmpeg', '-i', file_path, '-af', 'volumedetect', '-f', 'null', '-'],
                capture_output=True,
                timeout=10,
                text=True
            )
            # Parse stderr for "max_volume: X dB"
            for line in result.stderr.split('\n'):
                if 'max_volume' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'max_volume:' and i + 1 < len(parts):
                            try:
                                return float(parts[i + 1])
                            except ValueError:
                                pass
        except Exception as e:
            logger.error(f"Failed to get audio level: {e}")
        return None

    @staticmethod
    def check_file_integrity(file_path: str) -> Tuple[bool, str]:
        """Check if file is not corrupted."""
        if not os.path.isfile(file_path):
            return False, "File not found"

        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', file_path],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return True, ""
            return False, "Invalid or corrupted file"
        except Exception as e:
            return False, str(e)

    @classmethod
    def validate_clip(cls, file_path: str, source: str = "unknown") -> Dict[str, any]:
        """
        Comprehensive clip validation.

        Returns:
            {
                'valid': bool,
                'errors': [list of errors],
                'warnings': [list of warnings],
                'metrics': {duration, audio_level, ...}
            }
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'metrics': {}
        }

        # Check file integrity
        is_valid, msg = cls.check_file_integrity(file_path)
        if not is_valid:
            result['valid'] = False
            result['errors'].append(f"File integrity: {msg}")
            return result

        # Check duration
        duration = cls.get_clip_duration(file_path)
        if duration is None:
            result['valid'] = False
            result['errors'].append("Could not determine clip duration")
            return result

        result['metrics']['duration_seconds'] = duration

        if duration < cls.MIN_CLIP_DURATION:
            result['valid'] = False
            result['errors'].append(f"Clip too short ({duration:.1f}s, min {cls.MIN_CLIP_DURATION}s)")

        if duration > cls.MAX_CLIP_DURATION:
            result['valid'] = False
            result['errors'].append(f"Clip too long ({duration:.1f}s, max {cls.MAX_CLIP_DURATION}s)")

        # Check audio level
        audio_level = cls.get_audio_level(file_path)
        if audio_level is not None:
            result['metrics']['audio_level_db'] = audio_level

            if audio_level < cls.MIN_AUDIO_LEVEL:
                result['warnings'].append(f"Audio very quiet ({audio_level:.1f}dB, recommended > {cls.MIN_AUDIO_LEVEL}dB)")

            if audio_level < -80:  # Essentially silent
                result['valid'] = False
                result['errors'].append(f"Audio is silent ({audio_level:.1f}dB)")

        result['metrics']['source'] = source
        return result


class CaptionValidator:
    """Validates caption quality."""

    MIN_CAPTION_LENGTH = 3  # characters
    MAX_CAPTION_LENGTH = 100  # characters
    HALLUCINATION_KEYWORDS = ['[INAUDIBLE]', '[MUSIC]', '[SILENCE]']  # Common Whisper hallucinations

    @staticmethod
    def validate_caption(text: str) -> Tuple[bool, List[str]]:
        """
        Validate a single caption line.

        Returns (is_valid, [list of issues])
        """
        issues = []

        if len(text) < CaptionValidator.MIN_CAPTION_LENGTH:
            issues.append(f"Caption too short ({len(text)} chars)")
            return False, issues

        if len(text) > CaptionValidator.MAX_CAPTION_LENGTH:
            issues.append(f"Caption too long ({len(text)} chars, max {CaptionValidator.MAX_CAPTION_LENGTH})")

        # Check for common hallucinations
        for keyword in CaptionValidator.HALLUCINATION_KEYWORDS:
            if keyword in text:
                issues.append(f"Potential Whisper hallucination: {keyword}")

        return len(issues) == 0, issues

    @staticmethod
    def validate_srt(srt_path: str) -> Dict[str, any]:
        """
        Validate SRT subtitle file.

        Returns quality metrics and issues.
        """
        result = {
            'valid': True,
            'total_captions': 0,
            'short_captions': [],
            'long_captions': [],
            'suspect_captions': [],
            'issues': []
        }

        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Simple SRT parsing
            blocks = content.strip().split('\n\n')

            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) < 3:
                    continue

                # Last line is the caption text
                caption_text = ' '.join(lines[2:]).strip()

                if not caption_text:
                    continue

                result['total_captions'] += 1
                is_valid, issues = CaptionValidator.validate_caption(caption_text)

                if not is_valid:
                    result['suspect_captions'].append({
                        'text': caption_text,
                        'issues': issues
                    })
                    if len(caption_text) < CaptionValidator.MIN_CAPTION_LENGTH:
                        result['short_captions'].append(caption_text)
                    elif len(caption_text) > CaptionValidator.MAX_CAPTION_LENGTH:
                        result['long_captions'].append(caption_text)

        except Exception as e:
            result['valid'] = False
            result['issues'].append(f"Failed to parse SRT: {str(e)}")

        return result


class QualityControlManager:
    """Main QC orchestrator."""

    def __init__(self, strict_mode: bool = False):
        """
        Initialize QC manager.

        Args:
            strict_mode: If True, fail on warnings. If False, only fail on errors.
        """
        self.strict_mode = strict_mode
        self.validation_log = []

    def validate_all_clips(self, clips_dir: str) -> Dict[str, any]:
        """
        Validate all clips in directory.

        Returns summary of validation results.
        """
        summary = {
            'total_clips': 0,
            'valid_clips': 0,
            'invalid_clips': [],
            'warnings': []
        }

        if not os.path.isdir(clips_dir):
            summary['invalid_clips'].append({'file': clips_dir, 'error': 'Directory not found'})
            return summary

        for clip_file in os.listdir(clips_dir):
            if not clip_file.endswith('.mp4'):
                continue

            clip_path = os.path.join(clips_dir, clip_file)
            summary['total_clips'] += 1

            validation = ClipValidator.validate_clip(clip_path, source=clip_file)

            if validation['valid']:
                summary['valid_clips'] += 1
            else:
                summary['invalid_clips'].append({
                    'file': clip_file,
                    'errors': validation['errors'],
                    'warnings': validation['warnings']
                })

        return summary

    def print_summary(self, summary: Dict):
        """Print validation summary."""
        print("\n" + "=" * 70)
        print("📊 Quality Control Report")
        print("=" * 70)
        print(f"Total clips: {summary['total_clips']}")
        print(f"Valid clips: {summary['valid_clips']}")
        print(f"Invalid clips: {len(summary['invalid_clips'])}")

        if summary['invalid_clips']:
            print("\n❌ Issues found:")
            for clip in summary['invalid_clips']:
                print(f"  • {clip['file']}")
                for error in clip.get('errors', []):
                    print(f"    ✗ {error}")
                for warning in clip.get('warnings', []):
                    print(f"    ⚠ {warning}")

        print("=" * 70 + "\n")

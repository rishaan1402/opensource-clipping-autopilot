"""
clipping.studio — Video Rendering Engine

Thin compatibility entry point for the Studio pipeline.
Public API is re-exported from internal modules under clipping/studio/.
"""

import importlib.util
import os

FIREFOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"
)


def _load_studio_internal_module(file_name: str, module_alias: str):
    """
    Load an internal `clipping/studio/*.py` module by file path.

    Args:
        file_name: Python filename inside `clipping/studio`.
        module_alias: Unique import alias used by importlib.

    Returns:
        Loaded Python module object.
    """
    module_path = os.path.join(os.path.dirname(__file__), "studio", file_name)
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load internal module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_helpers = _load_studio_internal_module("helpers.py", "clipping_studio_helpers")
_ffmpeg_utils = _load_studio_internal_module("ffmpeg_utils.py", "clipping_studio_ffmpeg_utils")
_core = _load_studio_internal_module("core.py", "clipping_studio_core")

format_seconds = _helpers.format_seconds
escape_ffmpeg_filter_value = _helpers.escape_ffmpeg_filter_value
detect_video_encoder = _ffmpeg_utils.detect_video_encoder
get_ts_encode_args = _ffmpeg_utils.get_ts_encode_args
get_mp4_encode_args = _ffmpeg_utils.get_mp4_encode_args
open_ffmpeg_video_writer = _ffmpeg_utils.open_ffmpeg_video_writer
build_ffmpeg_progress_cmd = _ffmpeg_utils.build_ffmpeg_progress_cmd
run_ffmpeg_with_progress = _ffmpeg_utils.run_ffmpeg_with_progress

get_face_detector = _core.get_face_detector
quick_face_motion_probe = _core.quick_face_motion_probe
estimate_speaker_count_from_video = _core.estimate_speaker_count_from_video
download_google_font = _core.download_google_font
register_fonts_for_libass = _core.register_fonts_for_libass
prepare_typography_font = _core.prepare_typography_font
get_local_bgm_file = _core.get_local_bgm_file
build_bgm_filter = _core.build_bgm_filter
download_pexels_broll = _core.download_pexels_broll
crop_center_broll = _core.crop_center_broll
create_video_hybrid = _core.create_video_hybrid
create_ass_file = _core.create_ass_file
prepare_glitch_video = _core.prepare_glitch_video
download_transition_raw = _core.download_transition_raw
download_all_transitions = _core.download_all_transitions
get_random_transition = _core.get_random_transition
prepare_transition_clip = _core.prepare_transition_clip
TMP_TRANSITION_POOL = _core.TMP_TRANSITION_POOL
create_thumbnail = _core.create_thumbnail
create_video_split_screen = _core.create_video_split_screen
create_video_camera_switch = _core.create_video_camera_switch
_get_render_dims = _core._get_render_dims
_is_vertical_ratio = _core._is_vertical_ratio
process_clip = _core.process_clip

import html
import importlib.util
import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import textwrap
import time
import urllib.parse
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
import requests
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from PIL import Image, ImageDraw, ImageFont
from yt_dlp import YoutubeDL

FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"

def _load_studio_internal_module(file_name: str, module_alias: str):
    module_path = os.path.join(os.path.dirname(__file__), file_name)
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_helpers = _load_studio_internal_module("helpers.py", "clipping_studio_helpers")
_ffmpeg_utils = _load_studio_internal_module("ffmpeg_utils.py", "clipping_studio_ffmpeg_utils")
format_seconds = _helpers.format_seconds
escape_ffmpeg_filter_value = _helpers.escape_ffmpeg_filter_value
detect_video_encoder = _ffmpeg_utils.detect_video_encoder
get_ts_encode_args = _ffmpeg_utils.get_ts_encode_args
get_mp4_encode_args = _ffmpeg_utils.get_mp4_encode_args
open_ffmpeg_video_writer = _ffmpeg_utils.open_ffmpeg_video_writer
build_ffmpeg_progress_cmd = _ffmpeg_utils.build_ffmpeg_progress_cmd
run_ffmpeg_with_progress = _ffmpeg_utils.run_ffmpeg_with_progress


_FACE_DETECTOR = None

def get_face_detector(cfg):
    """
    Create or reuse a singleton MediaPipe face detector instance.

    Args:
        cfg: Runtime config that includes model path and model URL.

    Returns:
        mp_vision.FaceDetector: Initialized MediaPipe face detector singleton.

    Side Effects:
        Downloads the Mediapipe face detection model from the internet if it doesn't exist locally.
        Initializes a global `_FACE_DETECTOR` variable.

    Raises:
        urllib.error.URLError: If the model download fails.
        Exception: If Mediapipe initialization fails due to invalid model format.
    """
    global _FACE_DETECTOR

    if _FACE_DETECTOR is None:
        if not os.path.exists(cfg.file_mediapipe_model):
            urllib.request.urlretrieve(
                cfg.url_mediapipe_model, cfg.file_mediapipe_model
            )

        base_options = mp_python.BaseOptions(model_asset_path=cfg.file_mediapipe_model)
        _FACE_DETECTOR = mp_vision.FaceDetector.create_from_options(
            mp_vision.FaceDetectorOptions(
                base_options=base_options,
                min_detection_confidence=0.5,
            )
        )

    return _FACE_DETECTOR


def estimate_speaker_count_from_video(video_path: str, cfg) -> int:
    """
    Sample frames from the video to estimate the max number of visible faces.
    Used for automatically setting min_speakers for pyannote.

    Args:
        video_path (str): The absolute path to the video file.
        cfg: Runtime configuration that may specify 'face_detector' (e.g. 'yolo' or 'mediapipe').

    Returns:
        int: The estimated maximum number of speakers (faces) present in any sampled frame. Defaults to 2 if unsure.

    Side Effects:
        Downloads YOLO face detection model if it's set in config and doesn't exist.
        Prints scanning progress logs to stdout.

    Raises:
        Exception: General exceptions may occur during YOLO initialization, falling back to Mediapipe.
    """
    import cv2

    print("🔍 Auto-detecting speaker count via visual scanning...", flush=True)

    yolo_model = None
    detector = None

    if cfg.face_detector == "yolo":
        from ultralytics import YOLO
        import logging

        logging.getLogger("ultralytics").setLevel(logging.ERROR)
        try:
            model_name = f"yolov{cfg.yolo_size}-face.pt"
            yolo_model = YOLO(model_name)
        except Exception as e:
            print(f"⚠️ YOLO face detect failed: {e}. Falling back to Mediapipe.")
            cfg.face_detector = "mediapipe"

    if cfg.face_detector != "yolo":
        detector = get_face_detector(cfg)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 2

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_frames / fps if fps > 0 else 0

    if duration == 0:
        cap.release()
        return 2

    sample_count = 20
    step = duration / sample_count
    max_faces = 0

    for i in range(sample_count):
        t = i * step
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            continue

        faces_in_frame = 0

        if cfg.face_detector == "yolo" and yolo_model:
            results = yolo_model(frame, verbose=False)
            if results and len(results[0].boxes) > 0:
                faces_in_frame = len(results[0].boxes)
        else:
            mp_image = mp_python.Image(
                image_format=mp_python.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            results = detector.detect(mp_image)
            if results.detections:
                faces_in_frame = len(results.detections)

        if faces_in_frame > max_faces:
            max_faces = faces_in_frame

    cap.release()
    print(f"   ✅ Found a maximum of {max_faces} faces in a single frame.", flush=True)
    return max(1, max_faces)


_YOLO_FACE_MODEL = None


def _get_yolo_face_model(cfg):
    """Singleton cache — quick_face_motion_probe runs once per candidate, so
    reloading a YOLO model from disk each time would defeat the point."""
    global _YOLO_FACE_MODEL
    if _YOLO_FACE_MODEL is None:
        from ultralytics import YOLO
        import logging

        logging.getLogger("ultralytics").setLevel(logging.ERROR)
        _YOLO_FACE_MODEL = YOLO(f"yolov{cfg.yolo_size}-face.pt")
    return _YOLO_FACE_MODEL


def quick_face_motion_probe(
    video_path: str, start_time: float, end_time: float, cfg, sample_frames: int = 5, window_s: float = 3.0
) -> dict:
    """
    Cheap has_face / has_motion signal for a clip candidate's opening window,
    for clipping.phase1.monetization's VVSA scoring — run at scoring time
    (before any candidate is chosen to render), not during the full per-frame
    crop-tracking pass that already runs later for whichever clips get
    rendered. Only a handful of frames are read/decoded here, not the whole
    clip, which is what keeps this cheap enough to run on every candidate.

    Honors cfg.face_detector (mediapipe or yolo) rather than hardcoding
    either — MediaPipe's GPU delegate is known to hard-crash the whole
    process (a native SIGABRT, not a catchable Python exception) on some
    machines, exactly the failure this pipeline already routes around
    elsewhere via --face-detector yolo. Silently forcing mediapipe here
    would reintroduce that crash for anyone who chose yolo specifically to
    avoid it.

    Args:
        video_path: Path to the full source video (not a rendered clip).
        start_time, end_time: Candidate's window in the source video, seconds.
        window_s: Only the first `window_s` seconds are sampled — VVSA is
            specifically about the opening 1-3s, not the whole clip.

    Returns:
        {"has_face": bool, "has_motion": bool} — never None; a probe that
        fails to open the video, or to load its detector, degrades to
        {False, False} rather than raising, since this is a scoring signal,
        not a hard requirement.
    """
    import cv2

    result = {"has_face": False, "has_motion": False}
    use_yolo = getattr(cfg, "face_detector", "mediapipe") == "yolo"

    try:
        yolo_model = _get_yolo_face_model(cfg) if use_yolo else None
        detector = None if use_yolo else get_face_detector(cfg)
    except Exception as e:
        print(f"⚠️ Quick face/motion probe: failed to load detector ({e}). Skipping this probe.")
        return result

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return result

        probe_end = min(end_time, start_time + window_s)
        duration = max(probe_end - start_time, 0.01)
        step = duration / sample_frames

        prev_gray_small = None
        motion_scores = []

        for i in range(sample_frames):
            t = start_time + i * step
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                continue

            if use_yolo:
                results = yolo_model(frame, verbose=False)
                if results and len(results[0].boxes) > 0:
                    result["has_face"] = True
            else:
                mp_image = mp_python.Image(
                    image_format=mp_python.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                )
                detections = detector.detect(mp_image)
                if detections.detections:
                    result["has_face"] = True

            gray_small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36))
            if prev_gray_small is not None:
                diff = cv2.absdiff(gray_small, prev_gray_small)
                motion_scores.append(float(np.mean(diff)))
            prev_gray_small = gray_small

        cap.release()
        # Empirical threshold on mean 0-255 grayscale frame-diff at 64x36 —
        # a static talking-head shot lands well under 5; a hard cut, camera
        # pan, or scene change well over it.
        if motion_scores and max(motion_scores) > 8.0:
            result["has_motion"] = True

    except Exception as e:  # noqa: BLE001 — this is a soft scoring signal, never fatal
        print(f"⚠️ Quick face/motion probe failed ({start_time:.1f}s-{end_time:.1f}s): {e}")

    return result



"""
clipping.config — Master Configuration (Dashboard)

Stores all default values and builds the config from CLI args.
"""

import argparse
import os
from types import SimpleNamespace

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .rights import SOURCE_RIGHTS_CHOICES, validate_source_rights_args
from .creators_db import default_db_path as _default_creators_db_path

# ==============================================================================
# DEFAULT VALUES  (exactly matches notebook Cell 0)
# ==============================================================================

BASE_DIR = os.getcwd()
FONT_DIR = os.path.abspath(os.path.join(BASE_DIR, "custom_fonts"))

# 1. PENGATURAN UTAMA
JUMLAH_CLIP = 7
PILIHAN_RASIO = "9:16"

# 2. PENGATURAN KONTEN & HOOK
MAX_KATA_PER_SUBTITLE = 5
DURASI_HOOK = 3
USE_BROLL = True
USE_HOOK_GLITCH = True
USE_SPLIT_SCREEN = False
USE_CAMERA_SWITCH = False
DIARIZATION_NUM_SPEAKERS = "auto"
SWITCH_HOLD_DURATION = 2.0
SWITCH_BLEND_DURATION = 0.0  # 0 = instant snap, >0 = smooth blend in seconds

# Source Platform
SOURCE_PLATFORM = "youtube"

# 3. PENGATURAN SUBTITLE & TIPOGRAFI (ASS STYLE)
USE_ADVANCED_TEXT = False
USE_ADVANCED_TEXT_ON_HOOK = False
USE_KARAOKE_EFFECT = True

GAYA_FONT_AKTIF = "HORMOZI"

FONT_LIST = {
    "DEFAULT": {
        "primary": {
            "nama": "Montserrat Black",
            "file": "Montserrat-Black.ttf",
            "url": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf",
            "bold": 1,
        },
        "accent": {
            "nama": "Montserrat Medium",
            "file": "Montserrat-Medium.ttf",
            "url": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Medium.ttf",
            "bold": 0,
        },
    },
    "STORYTELLER": {
        "primary": {
            "nama": "Inter",
            "file": "Inter-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "accent": {
            "nama": "Lora",
            "file": "Lora-Bold.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/lora@latest/latin-700-normal.ttf",
            "bold": 1,
        },
    },
    "HORMOZI": {
        "primary": {
            "nama": "Montserrat",
            "file": "Montserrat-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "accent": {
            "nama": "Anton",
            "file": "Anton-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/anton@latest/latin-400-normal.ttf",
            "bold": 0,
        },
    },
    "CINEMATIC": {
        "primary": {
            "nama": "Roboto",
            "file": "Roboto-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/roboto@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "accent": {
            "nama": "Bebas Neue",
            "file": "BebasNeue-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@latest/latin-400-normal.ttf",
            "bold": 0,
        },
    },
}

# Khusus 9:16 (Vertikal)
ASS_ALIGN_916 = 2
ASS_MARGIN_916 = 450
ASS_FONT_916 = 90
SCALE_ACCENT_WORD_916 = ASS_FONT_916 + 120

# Khusus 16:9 (Horizontal)
ASS_ALIGN_169 = 2
ASS_MARGIN_169 = 70
ASS_FONT_169 = 80
SCALE_ACCENT_WORD_169 = ASS_FONT_169 + 120

# Warna Kata Khusus  (Format ASS: BGR -> &H[Blue][Green][Red]&)
ACCENT_WORD_COLOR = "&HFFFFFF&"

# 4. PENGATURAN ASSET EKSTERNAL
THUMBNAIL_FONT_NAME = "Montserrat-Black.ttf"
URL_FONT_THUMBNAIL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf"
)

URL_GLITCH_VIDEO = "https://www.youtube.com/watch?v=5nBcNRYmjs0"
URL_MEDIAPIPE_MODEL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite"

# 5. PENGATURAN Auto-BGM & Audio Ducking
USE_AUTO_BGM = True
BGM_BASE_VOLUME = 0.25
BGM_MODE = "ducking"  # 'ducking' = sidechain compress, 'background' = constant volume mix

# List of supported moods (matching folder names in assets/bgm/)
BGM_MOODS = ["chill", "epic", "sad", "upbeat", "suspense"]
BGM_DIR = os.path.abspath(os.path.join(BASE_DIR, "assets", "bgm"))

# Whisper
WHISPER_MODEL = "large-v3"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"
DOWNLOAD_SOURCE_HEIGHT = "max"
VIDEO_QUALITY_CQ = 23
VIDEO_QUALITY_CRF = 20
VIDEO_PRESET = "auto"
VIDEO_SCALE_ALGO = "lanczos"
RENDER_OUTPUT_HEIGHT = 1080

# AI Provider
AI_PROVIDER = "gemini"
NVIDIA_MODEL = "deepseek-ai/deepseek-v4-pro"
GROQ_MODEL = "openai/gpt-oss-120b"
# Groq's free tier TPM budget (8,000 for gpt-oss-20b/120b, observed directly from a live
# account) is blown by a full transcript once the source video runs much past ~10 minutes —
# this is the input prompt size, not something --max-tokens or retries can work around.
# Above this duration, skip straight to the Gemini fallback instead of wasting three
# guaranteed-to-fail Groq attempts (and the wait between them) first.
GROQ_MAX_VIDEO_DURATION_SECONDS = 600
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACK_MODEL = "gemini-3.6-flash"

# Local model served via vLLM's OpenAI-compatible API (e.g. on Kaggle's dual-T4 GPUs).
# AWQ quantization + tensor_parallel_size=2 lets a 32B-class model fit across both 16GB T4s.
LOCAL_MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
LOCAL_BASE_URL = "http://localhost:8000/v1"

# BGE semantic dedup — catches the LLM picking two candidates that are secretly the
# same moment restated, which hash-based dedup (clipping.phase1.deduplication) can't see.
# bge-small is a good speed/quality tradeoff for this: it runs once per candidate per
# video, not in a hot loop, so bge-base would also be fine if quality matters more here.
BGE_MODEL = "BAAI/bge-small-en-v1.5"
SEMANTIC_DEDUP_THRESHOLD = 0.92


# ==============================================================================
# CLI PARSER
# ==============================================================================


def _parse_speakers(val: str) -> str | int:
    if val.lower() == "auto":
        return "auto"
    try:
        return int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{val}' is not a valid integer or 'auto'")


def _parse_download_height(val: str) -> str | int:
    """
    Parse desired download source height.

    Accepts:
    - `max` to always prefer the highest available quality.
    - positive integers like 1080, 1440, 2160 to cap source resolution.
    """
    if val.lower() == "max":
        return "max"
    try:
        parsed = int(val)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"'{val}' is not valid. Use 'max' or an integer height (e.g. 1080, 1440, 2160)."
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Download source height must be a positive integer.")
    return parsed

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="🎬 OpenSource Clipping — AI Auto-Clipper & Teaser Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Pengaturan utama ---
    p.add_argument(
        "--url", "-u", required=False, default=None,
        help="Video URL to process (supports YouTube, TikTok, Instagram, Google Drive). Required unless --story-mode or --batch-file is used.",
    )
    p.add_argument(
        "--batch-file",
        default=None,
        help="Path to a CSV/JSON/TXT file listing multiple videos to process in sequence "
             "(CSV columns: url,title,tags). Each item gets its own isolated output directory "
             "under outputs/batch/. Mutually exclusive with --url.",
    )
    p.add_argument(
        "--source",
        choices=["youtube", "tiktok", "instagram", "gdrive"],
        default=SOURCE_PLATFORM,
        help="Video source platform. Determines download behavior and subtitle availability.",
    )
    p.add_argument(
        "--tiktok",
        action="store_true",
        default=False,
        help="[DEPRECATED] Use --source tiktok instead.",
    )
    p.add_argument(
        "--clips",
        "-n",
        type=int,
        default=JUMLAH_CLIP,
        help="Number of highlight clips to generate",
    )
    p.add_argument(
        "--ratio",
        "-r",
        default=PILIHAN_RASIO,
        choices=["9:16", "16:9", "1:1", "3:4", "4:5"],
        help="Output aspect ratio",
    )
    p.add_argument(
        "--source-height",
        type=_parse_download_height,
        default=DOWNLOAD_SOURCE_HEIGHT,
        help="Preferred source download max height. Use 'max' to fetch highest available quality.",
    )
    p.add_argument(
        "--cookies-file",
        default=None,
        help="Path to a Netscape-format cookies.txt (exported from a real logged-in YouTube "
        "session) for yt-dlp to authenticate with. Fixes YouTube's 'Sign in to confirm "
        "you're not a bot' block, which cloud/datacenter IPs (Kaggle, Colab, etc.) trip "
        "far more often than residential ones.",
    )
    p.add_argument(
        "--render-height",
        default=str(RENDER_OUTPUT_HEIGHT),
        help="Target output height for the render. Use 'source' to match the source video height, or a number (e.g. 1080, 1440).",
    )

    # --- Konten & Hook ---
    p.add_argument(
        "--words-per-sub",
        type=int,
        default=MAX_KATA_PER_SUBTITLE,
        help="Max words per karaoke subtitle group",
    )
    p.add_argument(
        "--hook-duration",
        type=int,
        default=DURASI_HOOK,
        help="Hook teaser duration in seconds",
    )
    p.add_argument(
        "--hook-source",
        default=None,
        help="Google Drive URL or local path for a single custom hook video (.mp4)",
    )
    p.add_argument(
        "--hook-source-start",
        type=float,
        default=0.0,
        help="Start time in seconds for the custom hook video",
    )
    p.add_argument("--no-broll", action="store_true", help="Disable B-roll footage")
    p.add_argument("--no-hook", action="store_true", help="Disable hook glitch teaser")
    p.add_argument("--no-bgm", action="store_true", help="Disable background music")
    p.add_argument(
        "--bgm-mode",
        choices=["ducking", "background"],
        default=BGM_MODE,
        help="BGM mixing mode: 'ducking' (sidechain compress — BGM auto-lowers during speech) or 'background' (constant low volume mix)",
    )
    p.add_argument(
        "--no-karaoke",
        action="store_true",
        help="Disable karaoke highlight effect (use clean text instead)",
    )
    p.add_argument(
        "--split-screen",
        action="store_true",
        default=USE_SPLIT_SCREEN,
        help="Enable split-screen mode for podcast with 2 speakers (9:16 only, requires HF_TOKEN for Pyannote)",
    )
    p.add_argument(
        "--diarization-speakers",
        type=_parse_speakers,
        default=DIARIZATION_NUM_SPEAKERS,
        help="Number of speakers for diarization, or 'auto' to auto-detect visually (used with --split-screen or --camera-switch)",
    )
    p.add_argument(
        "--camera-switch",
        action="store_true",
        default=USE_CAMERA_SWITCH,
        help="Enable camera-switch mode for podcast (9:16 only, requires HF_TOKEN). "
        "Mutually exclusive with --split-screen; split-screen takes precedence if both are set.",
    )
    p.add_argument(
        "--switch-hold-duration",
        type=float,
        default=SWITCH_HOLD_DURATION,
        help="Minimum seconds to hold on the current speaker before switching cameras (camera-switch mode only)",
    )
    p.add_argument(
        "--switch-blend-duration",
        type=float,
        default=SWITCH_BLEND_DURATION,
        help="Blend duration when switching speakers (0 = instant snap, 0.2 = smooth 200ms transition). Default is 0 (instant snap).",
    )
    p.add_argument(
        "--no-subs",
        action="store_true",
        help="Disable all subtitle rendering (useful if you only want the video without text)",
    )
    p.add_argument(
        "--dynamic-split",
        action="store_true",
        help="Automatically switch between full-screen (1 speaker) and split-screen (2 speakers) based on who is talking. Only active with --split-screen.",
    )
    p.add_argument(
        "--split-trigger",
        choices=["diarization", "face"],
        default="diarization",
        help="The trigger used to decide when to split the screen. 'diarization' uses audio (who is talking), 'face' uses video (how many faces are visible).",
    )


    # --- Split Screen Optimizations ---
    p.add_argument(
        "--split-zoom",
        type=float,
        default=1.0,
        help="Zoom factor for split-screen panels (e.g. 1.2, 1.5). Default is 1.0 (no zoom).",
    )
    p.add_argument(
        "--split-v-align",
        type=float,
        default=0.5,
        help="Vertical alignment for split-screen panels (0.0=top, 0.5=center, 1.0=bottom). Default is 0.5 (center).",
    )
    p.add_argument(
        "--split-auto-zoom",
        action="store_true",
        help="Automatically zoom in each split-screen panel until only one person is visible in each frame.",
    )
    p.add_argument(
        "--split-max-zoom",
        type=float,
        default=2.5,
        help="Maximum zoom factor allowed for auto-zoom (default: 2.5).",
    )


    # --- Subtitle & Tipografi ---
    p.add_argument(
        "--font-style",
        default=GAYA_FONT_AKTIF,
        choices=["DEFAULT", "STORYTELLER", "HORMOZI", "CINEMATIC"],
        help="Font style preset",
    )
    p.add_argument(
        "--advanced-text",
        action="store_true",
        default=USE_ADVANCED_TEXT,
        help="Enable advanced kinetic typography",
    )
    p.add_argument(
        "--advanced-text-hook",
        action="store_true",
        default=USE_ADVANCED_TEXT_ON_HOOK,
        help="Enable advanced typography on hook",
    )

    # --- Whisper ---
    p.add_argument(
        "--use-dlp-subs",
        action="store_true",
        help="Use yt-dlp to download auto/manual subtitles to speed up process (skipping Whisper if found)",
    )
    p.add_argument(
        "--whisper-model", default=WHISPER_MODEL, help="Faster-Whisper model size"
    )
    p.add_argument(
        "--whisper-device",
        default=WHISPER_DEVICE,
        choices=["cuda", "cpu", "auto"],
        help="Device for Whisper inference",
    )
    p.add_argument(
        "--whisper-compute-type",
        default=WHISPER_COMPUTE_TYPE,
        help="Compute type for Whisper (float16, int8, etc.)",
    )

    # --- Gemini & Face Detection ---
    p.add_argument(
        "--face-detector",
        choices=["mediapipe", "yolo"],
        default="mediapipe",
        help="AI model for face tracking (mediapipe is CPU, yolo uses GPU if available)",
    )
    p.add_argument(
        "--yolo-size",
        choices=["8n", "8s", "8m", "8n_v2", "9c"],
        default="8m",
        help="YOLO face model version/size (8n, 8s, 8m, 8n_v2, 9c). Only active if --face-detector yolo",
    )
    p.add_argument(
        "--ai-provider",
        choices=["gemini", "nvidia", "groq", "local"],
        default=AI_PROVIDER,
        help="AI provider for video analysis (gemini, nvidia, groq, or local).",
    )
    p.add_argument(
        "--nvidia-model",
        default=NVIDIA_MODEL,
        help="Model name for NVIDIA NIM API (e.g. deepseek-ai/deepseek-v3).",
    )
    p.add_argument(
        "--groq-model",
        default=GROQ_MODEL,
        help="Model name for Groq API (e.g. llama-3.3-70b-versatile, openai/gpt-oss-120b).",
    )
    p.add_argument(
        "--groq-max-duration-seconds",
        type=int,
        default=GROQ_MAX_VIDEO_DURATION_SECONDS,
        help="For source videos longer than this, don't attempt Groq — a full transcript past "
        "~10min blows Groq's free-tier TPM budget regardless of retries. Set to 0 to disable "
        "this check. What happens instead is controlled by --groq-oversized-fallback-gemini.",
    )
    p.add_argument(
        "--groq-oversized-fallback-gemini",
        action="store_true",
        help="When a video is too long for Groq (see --groq-max-duration-seconds), fall back "
        "to Gemini instead of skipping the video outright. Off by default — while Gemini's own "
        "free-tier daily quota is also exhausted, falling back just burns a guaranteed-fail "
        "10-attempt retry cycle per video instead of cleanly skipping to the next candidate.",
    )
    p.add_argument(
        "--local-model",
        default=LOCAL_MODEL,
        help="Model name/path served by the local vLLM OpenAI-compatible server "
        "(e.g. Qwen/Qwen2.5-32B-Instruct-AWQ). Must match what the vLLM server was started with.",
    )
    p.add_argument(
        "--local-base-url",
        default=LOCAL_BASE_URL,
        help="Base URL of the local vLLM OpenAI-compatible server.",
    )
    p.add_argument("--gemini-model", default=GEMINI_MODEL, help="Gemini model name")
    p.add_argument(
        "--gemini-fallback-model",
        default=GEMINI_FALLBACK_MODEL,
        help="Gemini fallback model name if main model fails",
    )
    p.add_argument(
        "--load-gemini-json",
        action="store_true",
        help="Load the saved gemini_response.json from outputs dir to bypass the AI generation step (useful for debugging)",
    )

    # --- Monetization Scoring ---
    mon_group = p.add_argument_group("Monetization Scoring")
    mon_group.add_argument(
        "--no-monetization-scoring",
        action="store_true",
        default=False,
        help="Disable monetization scoring; rank clips by AI viral_score only.",
    )
    mon_group.add_argument(
        "--quality-weight",
        type=float,
        default=0.7,
        help="Weight (0-1) given to the existing AI viral_score when combining scores.",
    )
    mon_group.add_argument(
        "--monetization-weight",
        type=float,
        default=0.3,
        help="Weight (0-1) given to the monetization score when combining with quality score.",
    )
    mon_group.add_argument(
        "--prosody-weight",
        type=float,
        default=0.0,
        help="Weight (0-1) given to the audio-prosody score (see Prosody Scoring group) "
        "when combining scores. Defaults to 0.0 (no-op) -- if set > 0, --quality-weight "
        "and --monetization-weight must be reduced so all three still sum to 1.0.",
    )

    # --- Prosody Scoring (Whisper audio-energy signal) ---
    prosody_group = p.add_argument_group("Prosody Scoring")
    prosody_group.add_argument(
        "--no-prosody-scoring",
        action="store_true",
        default=False,
        help="Disable audio-prosody feature extraction (pitch/energy variance, pause "
        "ratio) per candidate. Independent of --prosody-weight: this controls whether "
        "the signal is computed at all, not just whether it affects ranking.",
    )

    # --- Semantic Dedup (BGE) ---
    dedup_group = p.add_argument_group("Semantic Dedup")
    dedup_group.add_argument(
        "--no-semantic-dedup",
        action="store_true",
        default=False,
        help="Disable BGE-embedding semantic dedup of AI-selected candidates within a video.",
    )
    dedup_group.add_argument(
        "--semantic-dedup-threshold",
        type=float,
        default=SEMANTIC_DEDUP_THRESHOLD,
        help="Cosine similarity above which two candidates are treated as near-duplicates "
        "(the lower-viral_score one is dropped). 0-1, higher = stricter (fewer drops).",
    )
    dedup_group.add_argument(
        "--bge-model",
        default=BGE_MODEL,
        help="BGE sentence-embedding model name (sentence-transformers compatible) used for semantic dedup.",
    )

    # --- Checkpoint & Resume ---
    ckpt_group = p.add_argument_group("Checkpoint & Resume")
    ckpt_group.add_argument(
        "--no-checkpoint",
        action="store_true",
        default=False,
        help="Disable checkpointing; always redo download/transcribe/render even if previous outputs exist.",
    )
    ckpt_group.add_argument(
        "--reset-checkpoint",
        action="store_true",
        default=False,
        help="Clear any existing checkpoint state for this outputs dir before running (forces a full redo).",
    )

    # --- Quality Control ---
    qc_group = p.add_argument_group("Quality Control")
    qc_group.add_argument(
        "--no-quality-control",
        action="store_true",
        default=False,
        help="Skip post-render clip validation (duration/audio-level/integrity checks).",
    )
    qc_group.add_argument(
        "--qc-strict",
        action="store_true",
        default=False,
        help="Quality control warnings are treated as failures (removes affected clips from the final report as invalid).",
    )

    # --- Deduplication ---
    dedup_group = p.add_argument_group("Deduplication")
    dedup_group.add_argument(
        "--force-reprocess",
        action="store_true",
        default=False,
        help="Process the video even if this exact URL/file was already processed before (skips the duplicate warning gate).",
    )
    dedup_group.add_argument(
        "--dedup-db-dir",
        default=None,
        help="Directory for the deduplication tracking database (default: <outputs_dir>/../data).",
    )

    p.add_argument(
        "--box-face-detection",
        action="store_true",
        help="Draw a yellow bounding box around the detected face for debugging/tracking visualization",
    )
    p.add_argument(
        "--dev-mode",
        action="store_true",
        help="Enable developer visualization mode for 9:16 tracking (shows stabilization box and dimmed background)",
    )
    p.add_argument(
        "--dev-mode-with-output",
        action="store_true",
        help="Render BOTH the Dev Mode visualization AND the standard output video simultaneously.",
    )
    p.add_argument(
        "--dev-mode-with-output-merge",
        action="store_true",
        help="Render a merged side-by-side video of both Dev Mode and standard output.",
    )
    p.add_argument(
        "--track-lines",
        action="store_true",
        help="Draw crosshair tracking lines extending from the face box to the boundaries",
    )
    p.add_argument(
        "--static-crop",
        action="store_true",
        help="Disable face tracking and use static center crop for 1:1, 3:4, and 4:5 ratios",
    )

    # --- Smart Auto-Framing / Tracking ---
    p.add_argument(
        "--track-step",
        type=float,
        default=None,
        help="Face detection frequency in seconds (default: 0.25)",
    )
    p.add_argument(
        "--track-deadzone",
        type=float,
        default=None,
        help="Camera deadzone ratio (default: 0.15)",
    )
    p.add_argument(
        "--track-smooth",
        type=float,
        default=None,
        help="Camera smoothing speed (default: 0.30)",
    )
    p.add_argument(
        "--track-jitter",
        type=int,
        default=None,
        help="Pixel jitter threshold (default: 5)",
    )
    p.add_argument(
        "--track-snap",
        type=float,
        default=None,
        help="Face jump snap threshold (default: 0.25)",
    )
    p.add_argument(
        "--track-conf",
        type=float,
        default=0.55,
        help="[Experimental] Higher confidence threshold for face detection to prevent ghosts (default: 0.55)",
    )
    p.add_argument(
        "--track-smooth-window",
        type=int,
        default=12,
        help="[Experimental] Majority-vote window for layout stability (default: 12 frames)",
    )
    p.add_argument(
        "--scene-cut-threshold",
        type=int,
        default=18,
        help="[Experimental] Visibility change threshold to detect camera cuts and reset layout history (default: 18)",
    )
    p.add_argument(
        "--track-iou-threshold",
        type=float,
        default=0.2,
        help="[Experimental] Box overlap threshold to merge duplicate detections (default: 0.2)",
    )
    p.add_argument(
        "--video-bitrate",
        default="auto",
        help="Target video bitrate (e.g. 8M, 12M, auto). 'auto' scales based on resolution.",
    )
    p.add_argument(
        "--video-sharpen",
        action="store_true",
        help="Apply a subtle sharpening filter for clearer output.",
    )
    p.add_argument(
        "--video-cq",
        type=int,
        default=VIDEO_QUALITY_CQ,
        help="NVENC constant quality value (lower is sharper, bigger file).",
    )
    p.add_argument(
        "--video-crf",
        type=int,
        default=VIDEO_QUALITY_CRF,
        help="libx264 CRF value (lower is sharper, bigger file).",
    )
    p.add_argument(
        "--video-preset",
        default=VIDEO_PRESET,
        help="Override encoder preset for NVENC/libx264, or 'auto' to keep defaults.",
    )
    p.add_argument(
        "--video-scale-algo",
        choices=["lanczos", "bicubic", "bilinear", "area"],
        default=VIDEO_SCALE_ALGO,
        help="Resize algorithm for OpenCV scaling steps during rendering.",
    )

    # --- Hook V2 & Segment Trimming ---
    hook_v2_group = p.add_argument_group("Hook V2 & Segment Trimming")
    hook_v2_group.add_argument(
        "--hook-v2",
        action="store_true",
        default=False,
        help="Enable Multi-Hook Intro V2 mode (3-4 micro-hook clips with flash/glitch transitions).",
    )
    hook_v2_group.add_argument(
        "--hook-v2-items",
        type=int,
        default=3,
        help="Number of micro-hooks to generate in V2 mode.",
    )
    hook_v2_group.add_argument(
        "--hook-v2-style",
        default="controversial_fast_glitch",
        help="Style prompt hint for AI to pick the hook style.",
    )
    hook_v2_group.add_argument(
        "--white-flash-duration",
        type=float,
        default=0.12,
        help="Duration of white flash transition between hooks (seconds).",
    )
    hook_v2_group.add_argument(
        "--no-segment-trim",
        action="store_true",
        default=False,
        help="Disable AI segment trimming (render full start-to-end instead of keep_segments).",
    )
    hook_v2_group.add_argument(
        "--silence-trim",
        action="store_true",
        default=False,
        help="Instruct AI to aggressively trim silence/dead air from clips.",
    )

    # --- Story Clip Mode ---
    story_group = p.add_argument_group("Story Clip Mode")
    story_group.add_argument(
        "--story-mode",
        action="store_true",
        default=False,
        help="Enable Story Clip mode: assemble clips from multiple video sources using a JSON recipe.",
    )
    story_group.add_argument(
        "--story-recipe",
        default="story_recipe.json",
        help="Path to the story recipe JSON file.",
    )
    story_group.add_argument(
        "--sources-json",
        default="sources.json",
        help="Path to the sources registry JSON file.",
    )
    story_group.add_argument(
        "--story-output-dir",
        default=None,
        help="Output directory for story clips (default: outputs/story_clips).",
    )
    story_group.add_argument(
        "--skip-download",
        action="store_true",
        default=False,
        help="Skip source downloads and use existing cached files.",
    )

    # --- Source Rights Gate ---
    rights_group = p.add_argument_group("Source Rights")
    rights_group.add_argument(
        "--source-rights",
        choices=SOURCE_RIGHTS_CHOICES,
        default="unknown",
        help=(
            "Declares why this source may legally be clipped and re-published: "
            "'owned' (you made it), 'licensed_cc' (re-verified against the YouTube "
            "Data API at process time), 'permissioned' (creator agreement on file — "
            "requires --creator-permission-id), 'transformed_commentary' (requires "
            "--voiceover; substantial original commentary as a fair-use position), "
            "or 'unknown' (default — fine for a manual one-off run; an unattended "
            "pipeline must refuse to auto-publish this bucket)."
        ),
    )
    rights_group.add_argument(
        "--creator-permission-id",
        type=int,
        default=None,
        help="Row id in the creators registry (clipping/creators_db.py) backing --source-rights permissioned.",
    )
    rights_group.add_argument(
        "--creators-db",
        default=None,
        help="Path to the creators registry SQLite file (default: <outputs_dir>/../data/creators.db).",
    )

    # --- Voice-Over Commentary Pipeline ---
    vo_group = p.add_argument_group("Voice-Over Commentary (TTS)")
    vo_group.add_argument(
        "--voiceover",
        action="store_true",
        default=False,
        help="Enable AI voice-over commentary mode using Gemini and edge-tts.",
    )
    vo_group.add_argument(
        "--voiceover-voice",
        default="en-GB-MaisieNeural",
        help="TTS voice for edge-tts (e.g. id-ID-ArdiNeural, en-US-AvaNeural).",
    )
    vo_group.add_argument(
        "--voiceover-lang",
        choices=["id", "en"],
        default="en",
        help="Language for the commentary script generation.",
    )
    vo_group.add_argument(
        "--voiceover-style",
        choices=["analysis", "reaction", "lesson", "summary"],
        default="analysis",
        help="Style of the generated commentary.",
    )
    vo_group.add_argument(
        "--voiceover-length",
        choices=["short", "normal", "long"],
        default="short",
        help="Length of the generated commentary (short: ~10s, normal: ~30s, long: ~50s).",
    )
    vo_group.add_argument(
        "--voiceover-volume",
        type=float,
        default=1.0,
        help="Volume of the voice-over audio (0.0 to 1.0+).",
    )
    vo_group.add_argument(
        "--original-volume",
        type=float,
        default=0.15,
        help="Volume of the original video audio when voice-over is active.",
    )
    vo_group.add_argument(
        "--edge-glow",
        action="store_true",
        default=False,
        help="Enable ambient edge glow effect on the entire clip (hook, clip, broll, voiceover). Without this flag, glow only appears on voice-over intro.",
    )
    vo_group.add_argument(
        "--edge-glow-mode",
        choices=["default", "smooth", "full"],
        default="smooth",
        help=(
            "Edge glow rendering strategy. "
            "'default': 10s loop (original, may stutter at loop point). "
            "'smooth': 10s loop with auto-adjusted speed for seamless looping. "
            "'full': render glow for the full video duration (no loop needed, "
            "heavier but zero stutter)."
        ),
    )

    # --- Watermark ---
    wm_group = p.add_argument_group("Watermark")
    wm_group.add_argument(
        "--watermark",
        action="store_true",
        default=False,
        help="Enable watermark overlay on rendered clips.",
    )
    wm_group.add_argument(
        "--text",
        default=None,
        help="Watermark text to overlay (e.g. 'Channel Name').",
    )
    wm_group.add_argument(
        "--image",
        default=None,
        help="Path to watermark image file (supports PNG, JPG, JPEG, WEBP). PNG with transparency recommended.",
    )
    wm_group.add_argument(
        "--opacity",
        type=int,
        default=70,
        help="Watermark opacity in percent (1-100). Default: 70.",
    )
    wm_group.add_argument(
        "--position",
        default="center-right",
        choices=[
            "top-left", "top-center", "top-right",
            "center-left", "center", "center-right",
            "bottom-left", "bottom-center", "bottom-right",
        ],
        help="Watermark position on the video frame.",
    )
    wm_group.add_argument(
        "--padding",
        type=int,
        default=0,
        help="Watermark padding from the nearest edge in pixels.",
    )
    wm_group.add_argument(
        "--watermark-font-size",
        type=int,
        default=0,
        help="Watermark font size in pixels. 0 = auto (3%% of frame height).",
    )
    wm_group.add_argument(
        "--watermark-scale",
        type=int,
        default=15,
        help="Watermark image height as %% of frame height (1-100). Default: 15.",
    )

    return p


def build_config(argv: list[str] | None = None) -> SimpleNamespace:
    """Parse CLI args and merge with defaults into a config namespace."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Validate: --url is required unless --story-mode or --batch-file is used
    if not args.story_mode and not args.url and not args.batch_file:
        parser.error("--url is required unless --story-mode or --batch-file is used.")
    if args.url and args.batch_file:
        parser.error("--url and --batch-file are mutually exclusive — pass one or the other.")
    if args.batch_file and not os.path.exists(args.batch_file):
        parser.error(f"--batch-file not found: {args.batch_file}")

    # Validate source-rights combinations (needs a resolved creators-db path,
    # computed the same way build_config resolves outputs_dir below — done
    # here, ahead of that point, since validation must happen before any
    # download/AI cost is spent).
    _creators_db_path = args.creators_db or _default_creators_db_path(
        os.path.abspath(os.path.join(os.getcwd(), "outputs"))
    )
    validate_source_rights_args(args, parser, _creators_db_path)

    # Validate monetization scoring weights
    if not args.no_monetization_scoring:
        total_w = args.quality_weight + args.monetization_weight + args.prosody_weight
        if abs(total_w - 1.0) > 1e-6:
            parser.error(
                f"--quality-weight + --monetization-weight + --prosody-weight must sum "
                f"to 1.0, got {total_w}"
            )

    # Validate watermark args
    if args.watermark:
        if not args.text and not args.image:
            parser.error("--watermark requires --text or --image.")
        if not (1 <= args.opacity <= 100):
            parser.error(f"--opacity must be between 1-100, got: {args.opacity}")
        if args.padding < 0:
            parser.error(f"--padding cannot be negative, got: {args.padding}")
        if args.watermark_font_size < 0:
            parser.error(f"--watermark-font-size cannot be negative, got: {args.watermark_font_size}")
        if not (1 <= args.watermark_scale <= 100):
            parser.error(f"--watermark-scale must be between 1-100, got: {args.watermark_scale}")
        if args.image:
            if not os.path.exists(args.image):
                parser.error(f"Watermark image file not found: {args.image}")
            valid_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
            if not args.image.lower().endswith(valid_exts):
                parser.error(
                    f"Unsupported watermark image format: {args.image}. "
                    f"Supported formats: {', '.join(valid_exts)}"
                )

    base_dir = os.getcwd()
    outputs_dir = os.path.abspath(os.path.join(base_dir, "outputs"))
    os.makedirs(outputs_dir, exist_ok=True)
    font_dir = os.path.abspath(os.path.join(base_dir, "custom_fonts"))
    os.makedirs(font_dir, exist_ok=True)

    cfg = SimpleNamespace(
        # Paths
        base_dir=base_dir,
        outputs_dir=outputs_dir,
        font_dir=font_dir,
        source_video_file=os.path.abspath(os.path.join(base_dir, "source_video.mp4")),
        file_font_thumbnail=os.path.abspath(
            os.path.join(base_dir, THUMBNAIL_FONT_NAME)
        ),
        file_mediapipe_model=os.path.abspath(
            os.path.join(base_dir, "blaze_face_full_range.tflite")
        ),
        # YOLO configs
        face_detector=args.face_detector,
        yolo_size=args.yolo_size,
        url_yolo_model=f"https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov{args.yolo_size}.pt",
        file_yolo_model=os.path.abspath(
            os.path.join(base_dir, f"face_yolov{args.yolo_size}.pt")
        ),
        # API keys (from env)
        api_key_gemini=os.environ.get("GOOGLE_API_KEY", ""),
        hf_token=os.environ.get("HF_TOKEN", ""),
        pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
        youtube_data_api_key=os.environ.get("YOUTUBE_DATA_API_KEY", ""),
        # Source rights gate
        source_rights=args.source_rights,
        creator_permission_id=args.creator_permission_id,
        creators_db_path=args.creators_db or _default_creators_db_path(outputs_dir),
        # Pengaturan utama
        source_platform="tiktok" if args.tiktok else args.source,
        source_url=args.url,
        batch_file=os.path.abspath(args.batch_file) if args.batch_file else None,
        clip_count=args.clips,
        aspect_ratio=args.ratio,
        download_source_height=args.source_height,
        cookies_file=args.cookies_file,
        render_output_height=args.render_height,
        # Konten & Hook
        max_words_per_subtitle=args.words_per_sub,
        hook_duration=args.hook_duration,
        hook_source=args.hook_source,
        hook_source_start=args.hook_source_start,
        # Hook V2 & Segment Trimming
        hook_v2=args.hook_v2,
        hook_v2_items=args.hook_v2_items,
        hook_v2_style=args.hook_v2_style,
        white_flash_duration=args.white_flash_duration,
        no_segment_trim=args.no_segment_trim,
        silence_trim=args.silence_trim,
        use_broll=not args.no_broll,
        use_hook_glitch=not args.no_hook,
        use_auto_bgm=not args.no_bgm,
        use_karaoke_effect=not args.no_karaoke,
        use_split_screen=args.split_screen,
        use_dynamic_split=args.dynamic_split,
        split_trigger=args.split_trigger,
        use_camera_switch=args.camera_switch,
        diarization_num_speakers=args.diarization_speakers,
        switch_hold_duration=args.switch_hold_duration,
        switch_blend_duration=args.switch_blend_duration,
        split_zoom=args.split_zoom,
        split_v_align=args.split_v_align,
        split_auto_zoom=args.split_auto_zoom,
        split_max_zoom=args.split_max_zoom,
        # Subtitle & Tipografi
        no_subs=args.no_subs,
        active_font_style=args.font_style,
        font_list=FONT_LIST,
        use_advanced_text=args.advanced_text,
        use_advanced_text_on_hook=args.advanced_text_hook,
        # ASS position values
        ass_align_916=ASS_ALIGN_916,
        ass_margin_916=ASS_MARGIN_916,
        ass_font_916=ASS_FONT_916,
        scale_accent_word_916=SCALE_ACCENT_WORD_916,
        ass_align_169=ASS_ALIGN_169,
        ass_margin_169=ASS_MARGIN_169,
        ass_font_169=ASS_FONT_169,
        scale_accent_word_169=SCALE_ACCENT_WORD_169,
        accent_word_color=ACCENT_WORD_COLOR,
        # Asset URLs
        url_font_thumbnail=URL_FONT_THUMBNAIL,
        url_glitch_video=URL_GLITCH_VIDEO,
        url_mediapipe_model=URL_MEDIAPIPE_MODEL,
        # BGM
        bgm_base_volume=BGM_BASE_VOLUME,
        bgm_mode=args.bgm_mode,
        bgm_moods=BGM_MOODS,
        bgm_dir=BGM_DIR,
        # Whisper
        use_dlp_subs=args.use_dlp_subs,
        whisper_model=args.whisper_model,
        whisper_device=args.whisper_device,
        whisper_compute_type=args.whisper_compute_type,
        # AI
        ai_provider=args.ai_provider,
        api_key_nvidia=os.environ.get("NVIDIA_API_KEY", ""),
        nvidia_model=args.nvidia_model,
        api_key_groq=os.environ.get("GROQ_API_KEY", ""),
        groq_model=args.groq_model,
        groq_max_duration_seconds=args.groq_max_duration_seconds,
        groq_oversized_fallback_gemini=args.groq_oversized_fallback_gemini,
        local_model=args.local_model,
        local_base_url=args.local_base_url,
        gemini_model=args.gemini_model,
        gemini_fallback_model=args.gemini_fallback_model,
        load_gemini_json=args.load_gemini_json,
        # Monetization Scoring
        enable_monetization_scoring=not args.no_monetization_scoring,
        monetization_quality_weight=args.quality_weight,
        monetization_weight=args.monetization_weight,
        prosody_weight=args.prosody_weight,
        # Prosody Scoring
        enable_prosody_scoring=not args.no_prosody_scoring,
        # Semantic Dedup
        enable_semantic_dedup=not args.no_semantic_dedup,
        semantic_dedup_threshold=args.semantic_dedup_threshold,
        bge_model=args.bge_model,
        # Checkpoint & Resume
        enable_checkpoint=not args.no_checkpoint,
        reset_checkpoint=args.reset_checkpoint,
        # Quality Control
        enable_quality_control=not args.no_quality_control,
        qc_strict=args.qc_strict,
        # Deduplication
        force_reprocess=args.force_reprocess,
        dedup_db_dir=args.dedup_db_dir,
        # Tracking Tuning
        track_step=args.track_step,
        track_deadzone=args.track_deadzone,
        track_smooth=args.track_smooth,
        track_jitter=args.track_jitter,
        track_snap=args.track_snap,
        track_conf=args.track_conf,
        track_smooth_window=args.track_smooth_window,
        scene_cut_threshold=args.scene_cut_threshold,
        track_iou_threshold=args.track_iou_threshold,
        video_quality_cq=args.video_cq,
        video_quality_crf=args.video_crf,
        video_bitrate=args.video_bitrate,
        video_sharpen=args.video_sharpen,
        video_preset=args.video_preset,
        video_scale_algo=args.video_scale_algo,
        box_face_detection=args.box_face_detection,
        dev_mode=args.dev_mode,
        dev_mode_with_output=args.dev_mode_with_output,
        dev_mode_with_output_merge=args.dev_mode_with_output_merge,
        track_lines=args.track_lines,
        static_crop=args.static_crop,
        # Story Clip Mode
        story_mode=args.story_mode,
        story_recipe_path=os.path.abspath(args.story_recipe) if args.story_recipe else None,
        sources_json_path=os.path.abspath(args.sources_json) if args.sources_json else None,
        story_output_dir=(
            os.path.abspath(args.story_output_dir)
            if args.story_output_dir
            else os.path.join(outputs_dir, "story_clips")
        ),
        skip_download=args.skip_download,
        # Voice-Over Commentary
        voiceover=args.voiceover,
        voiceover_voice=args.voiceover_voice,
        voiceover_lang=args.voiceover_lang,
        voiceover_style=args.voiceover_style,
        voiceover_length=args.voiceover_length,
        voiceover_volume=args.voiceover_volume,
        original_volume=args.original_volume,
        edge_glow=args.edge_glow,
        edge_glow_mode=args.edge_glow_mode,
        # Watermark
        watermark_enabled=args.watermark,
        watermark_text=args.text,
        watermark_image=args.image,
        watermark_opacity=args.opacity,
        watermark_position=args.position,
        watermark_padding=args.padding,
        watermark_font_size=args.watermark_font_size,
        watermark_scale=args.watermark_scale,
    )

    return cfg

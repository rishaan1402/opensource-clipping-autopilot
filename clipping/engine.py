"""
clipping.engine — Download, Transcription & Gemini AI Analysis

Maps to Cell 2 (The Engine) of the notebook.
"""

import json
import os
import re
import time

from yt_dlp import YoutubeDL
from faster_whisper import WhisperModel


# ==============================================================================
# TAHAP 1: DOWNLOAD VIDEO
# ==============================================================================

def _build_ydl_format_selector(download_source_height: str | int) -> str:
    """
    Build a yt-dlp format selector string for source-quality preference.
    """
    # Skip AV1 codec as it lacks HW acceleration on many platforms (e.g., Colab T4)
    # and causes decoding failures in OpenCV/FFmpeg software fallbacks.
    # Note: Using [vcodec!*=av01] to safely ensure it does not contain 'av01' anywhere.
    codec_filter = "[vcodec!*=av01]"

    if download_source_height == "max":
        return f"bestvideo{codec_filter}+bestaudio/best{codec_filter}"

    try:
        h_val = int(download_source_height)
    except (ValueError, TypeError):
        h_val = 0

    if 0 < h_val <= 1080:
        # For standard resolutions, strictly prefer native MP4 (H.264/AAC), ensuring no AV1 in mp4
        return (
            f"bestvideo[height<=?{h_val}][ext=mp4]{codec_filter}+bestaudio[ext=m4a]/"
            f"bestvideo[height<=?{h_val}]{codec_filter}+bestaudio/"
            f"best[height<=?{h_val}][ext=mp4]{codec_filter}/"
            f"best[height<=?{h_val}]{codec_filter}"
        )

    return (
        f"bestvideo[height<=?{download_source_height}]{codec_filter}+bestaudio/"
        f"best[height<=?{download_source_height}]{codec_filter}"
    )


_PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "gdrive": "Google Drive",
}


def _extract_gdrive_file_id(url: str) -> str | None:
    """Extract the Google Drive file ID from various URL formats."""
    import re as _re
    m = _re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = _re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def _download_gdrive(url: str, output_path: str) -> None:
    """Download a video from Google Drive using gdown (more reliable than yt-dlp)."""
    import gdown

    file_id = _extract_gdrive_file_id(url)
    if not file_id:
        raise RuntimeError(
            f"Tidak dapat mengekstrak file ID dari URL Google Drive: {url}\n"
            "      Format yang didukung:\n"
            "        • https://drive.google.com/file/d/FILE_ID/view\n"
            "        • https://drive.google.com/open?id=FILE_ID"
        )

    download_url = f"https://drive.google.com/uc?id={file_id}"
    print(f"      📥 File ID: {file_id}")
    gdown.download(download_url, output_path, quiet=False)


def _ydl_progress_hook(d: dict) -> None:
    """Render satu baris progress bar download dari data hook yt-dlp.

    yt-dlp mengunduh stream video dan audio secara terpisah, jadi hook ini
    dipanggil untuk masing-masing; newline saat "finished" menjaga tiap bar
    berada di barisnya sendiri.
    """
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        speed = d.get("speed")
        eta = d.get("eta")
        spd = f"{speed / 1024 / 1024:4.1f}MB/s" if speed else "  --MB/s"
        eta_s = f"{eta:>3}s" if eta is not None else " --s"
        if total:
            pct = downloaded / total * 100
            filled = int(20 * downloaded / total)
            bar = "█" * filled + " " * (20 - filled)
            print(
                f"\r      Unduh: {pct:3.0f}%|{bar}| "
                f"{downloaded / 1048576:.0f}/{total / 1048576:.0f}MB {spd} ETA {eta_s}   ",
                end="", flush=True,
            )
        else:
            # Ukuran tidak diketahui (live/streamed manifest) — tampilkan byte + speed saja.
            print(
                f"\r      Unduh: {downloaded / 1048576:.0f}MB {spd}   ",
                end="", flush=True,
            )
    elif status == "finished":
        print(flush=True)  # tutup baris bar untuk stream ini


def download_video(
    url: str,
    output_path: str,
    use_dlp_subs: bool = False,
    download_source_height: str | int = "max",
    source_platform: str = "youtube",
    cookies_file: str | None = None,
) -> dict:
    """
    Download a video to *output_path* with configurable source height.

    Parameters
    ----------
    source_platform : str
        One of ``"youtube"`` (default), ``"tiktok"``, ``"instagram"``,
        or ``"gdrive"``.

    Returns
    -------
    dict
        Source metadata needed by clipping.rights for license
        re-verification and attribution: video_id, title, uploader,
        channel_id, channel_url, webpage_url, license, platform.
        Best-effort — fields are None where yt-dlp/the platform doesn't
        expose them (always the case for source_platform="gdrive").
    """
    platform_label = _PLATFORM_LABELS.get(source_platform, source_platform)
    uses_youtube_format = source_platform == "youtube"
    source_info = {
        "video_id": None,
        "title": None,
        "uploader": None,
        "channel_id": None,
        "channel_url": None,
        "webpage_url": url,
        "license": None,
        "platform": source_platform,
    }

    print(f"[1/3] Mendownload video dari {platform_label}...")
    if download_source_height == "max":
        print("      🎯 Source quality: highest available", flush=True)
    else:
        print(f"      🎯 Source quality: up to {download_source_height}p", flush=True)

    # yt-dlp's default behavior is to skip downloading if a file already
    # exists at outtmpl — it does NOT check whether that file is actually
    # the URL being requested. Every run reusing the same output_path
    # (which this pipeline always does — video_asli.mp4) silently kept
    # whatever video was downloaded there FIRST, regardless of which URL
    # every subsequent call actually asked for. Removing any stale file
    # up front is the fix; relying on a yt-dlp option here would still
    # leave gdown's own file untouched for the "gdrive" platform below.
    if os.path.exists(output_path):
        os.remove(output_path)

    # --- Google Drive: use gdown instead of yt-dlp ---
    if source_platform == "gdrive":
        _download_gdrive(url, output_path)
        if not os.path.exists(output_path):
            raise RuntimeError(
                f"❌ Download dari Google Drive gagal — file tidak ditemukan di {output_path}"
            )
        print(f"      ✅ Video berhasil didownload dari Google Drive.", flush=True)
        return source_info

    # --- Build yt-dlp options per platform ---
    if uses_youtube_format:
        # YouTube: complex format selector + AV1 filter + remote components
        ydl_opts = {
            "format": _build_ydl_format_selector(download_source_height),
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "remote_components": ["ejs:github"],
            "progress_hooks": [_ydl_progress_hook],
            "extractor_args": {"youtube": ["player_client=android,web"]},
            "overwrites": True,
        }
    else:
        # TikTok / Instagram: ensure video and audio are merged
        # We explicitly prefer H.264 over H.265 (TikTok's bytevc1) to prevent 
        # PyAV/faster-whisper from crashing with IndexError on Kaggle/Colab.
        ydl_opts = {
            "format": "bestvideo[vcodec^=h264]+bestaudio/best[vcodec^=h264]/best",
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "progress_hooks": [_ydl_progress_hook],
            "overwrites": True,
        }

    if cookies_file:
        # Authenticates yt-dlp as a real signed-in browser session — the fix for YouTube's
        # "Sign in to confirm you're not a bot" bot-check, which datacenter/cloud IPs
        # (Kaggle, Colab, etc.) trip far more often than residential ones. A Netscape-format
        # cookies.txt exported from a real logged-in YouTube session (e.g. via a browser
        # extension), not something generated here — yt-dlp reads it directly.
        ydl_opts["cookiefile"] = cookies_file

    # --- Subtitle download — only supported for YouTube ---
    if use_dlp_subs and uses_youtube_format:
        print("      Mencoba mencari subtitle bahasa otomatis (en / id)...")
        import glob

        for lang in ["en", "id"]:
            ydl_opts_subs = ydl_opts.copy()
            ydl_opts_subs.update({
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [lang],
                "subtitlesformat": "json3",
                "skip_download": True,  # Hanya fokus download subtitle
            })

            try:
                with YoutubeDL(ydl_opts_subs) as ydl:
                    ydl.download([url])

                # Cek apakah json3 untuk bahasa ini benar-benar terdownload
                if glob.glob(output_path.replace(".mp4", f".*.json3")):
                    print(f"      ✅ Subtitle '{lang}' ditemukan. Melanjutkan ke video...")
                    break
            except Exception as e:
                print(f"      ⚠️ Gagal menarik subtitle '{lang}' ({e}). Mencoba opsi selanjutnya...")
    elif use_dlp_subs and not uses_youtube_format:
        print(f"      ℹ️ {platform_label} tidak menyediakan subtitle otomatis. Whisper akan digunakan.")

    # Jalankan download video terpisah dari urusan subtitle
    with YoutubeDL(ydl_opts) as ydl:
        # Extra step to verify resolution before downloading — also the only
        # place we have yt-dlp's parsed info dict, so pull source metadata
        # (uploader/channel/license) needed by clipping.rights here too.
        try:
            info = ydl.extract_info(url, download=False)
            best_h = info.get("height", "unknown")
            v_codec = info.get("vcodec", "unknown")
            print(f"      ✅ Mendownload: {best_h}p (Codec: {v_codec})", flush=True)

            source_info.update({
                "video_id": info.get("id"),
                "title": info.get("title"),
                "uploader": info.get("uploader") or info.get("channel"),
                "channel_id": info.get("channel_id"),
                "channel_url": info.get("channel_url") or info.get("uploader_url"),
                "webpage_url": info.get("webpage_url") or url,
                "license": info.get("license"),
            })
        except Exception as e:
            print(f"      ⚠️ Gagal mengecek info detail: {e}", flush=True)

        ydl.download([url])

    # --- Post-download verification ---
    if not os.path.exists(output_path):
        raise RuntimeError(
            f"❌ Download dari {platform_label} gagal — file video tidak ditemukan di {output_path}.\n"
            "      Pastikan URL valid dan bisa diakses secara publik."
        )

    return source_info


# ==============================================================================
# TAHAP 2: TRANSKRIPSI WHISPER & JSON3 FALLBACK
# ==============================================================================

def parse_youtube_json3_subs(json_path: str, max_words_per_subtitle: int = 5) -> tuple[str, list[dict]]:
    """
    Parse downloaded YouTube JSON3 subtitles into transkrip_lengkap and data_segmen.
    Returns empty string/list if parsing fails.
    """
    import json

    print("[2/3] Memproses subtitle JSON3 dari YouTube...")
    transkrip_lengkap = ""
    data_segmen = []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            subs_data = json.load(f)

        events = subs_data.get("events", [])

        flat_words = []
        for event in events:
            # YouTube timestamps are in ms
            t_start = event.get("tStartMs", 0) / 1000.0
            d_duration = event.get("dDurationMs", 0) / 1000.0
            event_end = t_start + d_duration

            segs = event.get("segs", [])
            for i, seg in enumerate(segs):
                text = seg.get("utf8", "")
                if not text.strip() or text == "\n":
                    continue

                # tOffsetMs is offset from t_start
                offset = seg.get("tOffsetMs", 0) / 1000.0
                seg_start = t_start + offset

                # Determine end of this segment
                if i < len(segs) - 1:
                    next_offset = segs[i + 1].get("tOffsetMs", 0) / 1000.0
                    seg_end = t_start + next_offset
                else:
                    seg_end = event_end

                if seg_end <= seg_start:
                    seg_end = seg_start + 1.0  # Fallback duration

                # Clean up YouTube subtitle artifacts
                clean_text = text.replace("\n", " ").replace("\u200b", "").strip()
                # Remove HTML tags (e.g., <i>, </i>, <b>, </b>, <font color="...">)
                clean_text = re.sub(r"<[^>]+>", "", clean_text)
                # Remove YouTube annotation brackets: [Music], [Applause], [Laughter], etc.
                clean_text = re.sub(r"\[[\w\s]+\]", "", clean_text)
                # Remove speaker change markers: >> 
                clean_text = re.sub(r">>\s*", "", clean_text)
                # Remove music symbols: ♪, ♫, etc.
                clean_text = re.sub(r"[♪♫♬♩]", "", clean_text)
                # Remove leading dashes often used for speaker identification
                clean_text = re.sub(r"^\s*-\s+", "", clean_text)
                # Collapse multiple spaces into one
                clean_text = re.sub(r"\s{2,}", " ", clean_text).strip()

                if clean_text:
                    # Memecah teks menjadi kata tunggal agar karaoke per-kata bekerja seperti whisper
                    words_in_seg = clean_text.split()
                    if not words_in_seg:
                        continue

                    duration_per_word = (seg_end - seg_start) / len(words_in_seg)

                    for w_idx, w_text in enumerate(words_in_seg):
                        w_start = seg_start + (w_idx * duration_per_word)
                        w_end = w_start + duration_per_word

                        flat_words.append({
                            "word": w_text,
                            "start": w_start,
                            "end": w_end,
                        })

        # Adjust end times based on the start time of the next word to prevent overlaps
        for i in range(len(flat_words) - 1):
            if flat_words[i]["end"] > flat_words[i + 1]["start"]:
                flat_words[i]["end"] = max(flat_words[i]["start"] + 0.1, flat_words[i + 1]["start"])

        # Group them into segments
        chunk_words = []
        chunk_start = 0.0

        for i, w in enumerate(flat_words):
            if len(chunk_words) == 0:
                chunk_start = w["start"]

            chunk_words.append(w)

            if len(chunk_words) == max_words_per_subtitle or i == len(flat_words) - 1:
                chunk_text = " ".join([cw["word"] for cw in chunk_words])
                chunk_end = w["end"]
                transkrip_lengkap += f"[{chunk_start:.1f} - {chunk_end:.1f}] {chunk_text}\n"

                data_segmen.append({
                    "start": chunk_start,
                    "end": chunk_end,
                    "words": chunk_words,
                })
                chunk_words = []

        return transkrip_lengkap, data_segmen

    except Exception as e:
        print(f"⚠️ Gagal memparsing JSON3: {e}")
        return "", []


def transcribe_video(
    video_path: str,
    max_words_per_subtitle: int = 5,
    model_size: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
) -> tuple[str, list[dict]]:
    """
    Transcribe *video_path* using Faster-Whisper.

    Returns
    -------
    transkrip_lengkap : str
        Human-readable transcript with timestamps.
    data_segmen : list[dict]
        Word-level segments grouped by *max_words_per_subtitle*.
    """
    print("[2/3] Memulai transkripsi dengan Faster-Whisper (Level Per-Kata)...")

    # Langkah-langkah ini berjalan tanpa output di dalam faster-whisper sebelum
    # segmen pertama dihasilkan, jadi kita umumkan tiap fase — kalau tidak, run
    # pertama di CPU (download model + decode seluruh audio) terlihat seperti hang.
    print(
        f"      ⏳ Memuat model Whisper '{model_size}' ({device})"
        " — unduhan pertama kali bisa memakan waktu...",
        flush=True,
    )
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print("      ⏳ Mendekode audio & mengekstrak fitur (belum ada output)...", flush=True)
    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)

    transkrip_lengkap = ""
    data_segmen: list[dict] = []

    # Progress bar berdasarkan timestamp audio. faster-whisper men-stream segmen
    # secara lazy, jadi bar dimajukan ke waktu akhir tiap segmen saat tiba.
    from tqdm import tqdm

    total_dur = round(info.duration, 2)
    progress = tqdm(
        total=total_dur,
        unit="s",
        desc="      Transkripsi",
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f}s [{elapsed}<{remaining}]",
    )

    for segment in segments:
        # Clamp agar floating-point drift melewati durasi tidak overshoot.
        progress.update(min(segment.end, total_dur) - progress.n)
        transkrip_lengkap += f"[{segment.start:.1f} - {segment.end:.1f}] {segment.text}\n"

        if segment.words:
            chunk_words: list[dict] = []
            chunk_start = 0.0

            for i, w in enumerate(segment.words):
                if len(chunk_words) == 0:
                    chunk_start = w.start

                chunk_words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

                if len(chunk_words) == max_words_per_subtitle or i == len(segment.words) - 1:
                    data_segmen.append({
                        "start": chunk_start,
                        "end": w.end,
                        "words": chunk_words,
                    })
                    chunk_words = []

    progress.update(total_dur - progress.n)  # snap ke 100% saat selesai
    progress.close()
    return transkrip_lengkap, data_segmen


# ==============================================================================
# TAHAP 3: ANALISIS GEMINI AI
# ==============================================================================

TARGET_ACCOUNTS = {
    "Knowledge": {
        "akun_tujuan": "Knowledge.Clips",
        "angle_desc": "If the angle is educational/informative: history, science, psychology, philosophy, astronomy, or book summaries — content that makes the viewer learn something interesting, not practical/how-to content.",
        "bio": "Educational clips on science, history & psychology. History | Science | Psychology | Philosophy | Space"
    },
    "GrowthAndMoney": {
        "akun_tujuan": "Growth.Clips",
        "angle_desc": "If the angle is productivity, self-improvement, motivation, personal finance/investing, business, or entrepreneurship — content that pushes the viewer toward action/change in their life or career.",
        "bio": "Insight on growth, productivity & finance. Productivity | Finance | Business | Motivation"
    },
    "SkillsAndLifestyle": {
        "akun_tujuan": "Skills.Clips",
        "angle_desc": "If the angle is a tutorial/practical skill viewers can apply immediately: coding, Excel, DIY, photography, language learning, cooking, or fitness.",
        "bio": "Practical tutorials to upgrade everyday skills. Coding | DIY | Photography | Cooking | Fitness"
    }
}

def _build_account_classification_prompt() -> str:
    lines = []
    for tipe, data in TARGET_ACCOUNTS.items():
        lines.append(f"- {tipe}: {data['angle_desc']}")
        lines.append(f"  (akun_tujuan: \"{data['akun_tujuan']}\", bio: \"{data['bio']}\")")
    return "\n".join(lines)


# ---- Retry Config ----
MAX_ATTEMPTS = 10
INITIAL_WAIT_SECONDS = 60
WAIT_INCREMENT_SECONDS = 30

# NVIDIA gets a shorter, separate retry budget: it's the primary provider when
# --ai-provider nvidia is set, but still falls back to Gemini's own full-length
# retry on total failure — a 10-attempt/60s+ budget here would double the worst-case
# wait per video on top of that fallback's own retries.
NVIDIA_MAX_ATTEMPTS = 3
NVIDIA_INITIAL_WAIT_SECONDS = 15
NVIDIA_WAIT_INCREMENT_SECONDS = 15
REQUEST_TIMEOUT_MS = 15 * 60 * 1000  # 15 menit
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _extract_status_code(exc: Exception):
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    match = re.search(r"\b(408|429|500|502|503|504)\b", str(exc))
    return int(match.group(1)) if match else None


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True

    code = _extract_status_code(exc)
    if code in RETRYABLE_STATUS_CODES:
        return True

    msg = str(exc).lower()
    keywords = (
        "timeout", "temporarily unavailable", "deadline",
        "connection reset", "connection aborted", "service unavailable",
    )
    return any(k in msg for k in keywords)


def _generate_json_with_retry(client, model, fallback_model, contents, config):
    last_exc = None
    status_code = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"[Gemini] Attempt {attempt}/{MAX_ATTEMPTS}...")

            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ValueError("Gemini mengembalikan response.text kosong.")

            return json.loads(text)

        except Exception as exc:
            last_exc = exc
            status_code = _extract_status_code(exc)
            retryable = _is_retryable(exc)

            print(
                f"[Gemini] Attempt {attempt}/{MAX_ATTEMPTS} gagal | "
                f"status={status_code} | error={exc}"
            )

            if (not retryable) or attempt == MAX_ATTEMPTS:
                break

            wait_seconds = INITIAL_WAIT_SECONDS + ((attempt - 1) * WAIT_INCREMENT_SECONDS)
            print(f"[Gemini] Retry lagi dalam {wait_seconds} detik...")
            time.sleep(wait_seconds)

    print(f"[Gemini] Percobaan dengan model utama ({model}) gagal.")
    if fallback_model:
        print(f"[Gemini] Mencoba satu kali lagi dengan fallback model ({fallback_model})...")
        try:
            response = client.models.generate_content(
                model=fallback_model,
                contents=contents,
                config=config,
            )
            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ValueError("Gemini fallback mengembalikan response.text kosong.")

            return json.loads(text)
        except Exception as exc_fallback:
            print(f"[Gemini] Fallback model gagal | error={exc_fallback}")
            raise RuntimeError(
                f"Gagal memanggil Gemini utama & fallback. "
                f"Laporan Utama status={status_code}, error={last_exc} | "
                f"Laporan Fallback error={exc_fallback}"
            ) from exc_fallback

    raise RuntimeError(
        f"Gagal memanggil Gemini setelah {MAX_ATTEMPTS} percobaan. Error terakhir: {last_exc}"
    ) from last_exc


# ==== KONFIGURASI DURASI KLIP ====
# Ubah nilai di bawah ini jika ingin mengganti batas durasi klip (dalam detik)
MIN_CLIP_DURATION = 20
MAX_CLIP_DURATION = 179

def get_analysis_prompt(transkrip_lengkap: str, jumlah_clip: int, durasi_hook: int, cfg=None) -> str:
    """Centralized prompt for both Gemini and NVIDIA providers."""
    # Build optional Hook V2 prompt section
    _hook_v2_prompt = ""
    if cfg and getattr(cfg, "hook_v2", False):
        _hook_v2_items = getattr(cfg, "hook_v2_items", 3)
        _hook_v2_style = getattr(cfg, "hook_v2_style", "controversial_fast_glitch")
        _hook_v2_prompt = f"""

HOOK V2 (MULTI-HOOK INTRO — REQUIRED):
- Besides the standard hook, also build a "hook_v2" containing {_hook_v2_items} short cuts (0.5-2 seconds) taken from the most striking/controversial/emotional moments inside the clip.
- Style: {_hook_v2_style}
- Each item must contain: start_time, end_time, and text (short on-screen text, 2-5 words).
- Items must be ordered from strongest to weakest.
- Transitions between items are added automatically (white flash / glitch) by the system.
- Fill the "hook_v2" field as an object with:
  - "enabled": true
  - "items": array of objects (start_time, end_time, text)
  - "transition": object with "type" ("white_flash" or "glitch")
"""

    # Build optional Segment Trimming prompt section
    _segment_prompt = ""
    if cfg and not getattr(cfg, "no_segment_trim", False):
        _silence_hint = ""
        if cfg and getattr(cfg, "silence_trim", False):
            _silence_hint = "\n- AGGRESSIVELY cut silent/dead-air parts. Don't include pauses longer than 0.5 seconds."
        _segment_prompt = f"""

SEGMENT-BASED TRIMMING (KEEP SEGMENTS — REQUIRED):
- For each clip, analyze whether there's a part that's less interesting, too silent, rambling, or filler in the middle.
- If so, split the clip into several "keep_segments" — only the best cuts are kept.
- Each segment contains: start_time and end_time.
- Segments must be chronologically ordered and must not overlap.
- If the whole clip duration is already tight and engaging, just make 1 segment covering the full duration.{_silence_hint}
- Fill the "keep_segments" field as an array of objects (start_time, end_time).
"""
    return f"""
You are an Art Director, Video Editor, and Short-Form Content Metadata Strategist for TikTok, Reels, and YouTube Shorts.

Read the following video transcript. Transcript format:
[start_second - end_second] text

MAIN TASK:
- Find the {jumlah_clip} most interesting, most powerful, most shareable, and most viral-potential moments to turn into short clips.
- Order clips by highest viral_score (most viral potential) to lowest. The "rank" is just a sequence number (1, 2, 3...).
- For each clip, produce clip timing, hook, typography plan, b-roll plan, selection reasoning, cross-platform metadata, and target-account classification.
- All output must be highly relevant to the clip's content, not the full video's content in general.

CLIP SELECTION & VIRAL-ABILITY RULES:
- Clip duration must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds.
- Look for moments containing one (or a combination — the more the stronger) of these patterns — these are the patterns that most often drive share/comment/watch-through on short-form:
  1. Curiosity gap — a question/tension that makes viewers HAVE to know the answer before scrolling on.
  2. Bold claim / controversial opinion — a bold statement that provokes agreement/disagreement.
  3. Pattern interrupt — something unexpected that subverts viewer expectations.
  4. Specific numbers/statistics — far more powerful than generic claims ("70% of people get this wrong" > "a lot of people get this wrong").
  5. Relatable pain point — a problem that makes viewers feel "this is so me".
  6. Transformation/reveal — before-after, a secret being revealed, an insight that shifts perspective.
  7. Mistake/warning — a common mistake people make without realizing it.
  8. Insider knowledge — feels like information that's rarely shared openly.
- Evaluate viral strength (viral-ability) and give a "viral_score" (1-100) representing how viral a clip could be.
  - 90-100: Very high fyp/viral potential — contains 2+ of the patterns above at once, extremely strong hook within <2 seconds.
  - 80-89: Engaging, contains 1 strong pattern, good performance potential.
  - 70-79: Standard, informative but maybe lacking punch, no clear viral pattern.
- Prioritize parts that stay interesting even watched without the full video's context (standalone value).
- Avoid clips that are too similar to each other — if there are 2 strong moments with the same angle, pick only the sharpest one.
- Don't pick clips that feel flat, rambling, generic, or lack a clear payoff.
- Prioritize SPECIFIC and CONCRETE moments over abstract/general ones — specific detail is far more shareable than generic advice.

ADAPTING TO CONTENT TYPE:
Adjust your clip-selection strategy to the type of video read from the transcript:
- Podcast/interview (2+ alternating voices): look for debate moments, unexpected answers, or a bold claim from one of the speakers.
- Solo monologue/talking-head: look for personal storytelling, insight delivered with full conviction, or a tone shift signaling an important point.
- Tutorial/how-to: look for the most actionable step, a common mistake being corrected, or an impressive end result — avoid boring technical steps without a clear visual/verbal payoff.
- Reaction/commentary/debate: look for sharp disagreement, a jab, or a turning point in the argument.
- Education/science/history: look for a surprising fact, a myth being debunked, or an analogy that makes a hard concept easy to understand.
If the content type isn't clear, use the general approach (curiosity gap + emotional intensity) as the default.

RETENTION & CLIP STRUCTURE RULES:
- Make sure the clip's first 3 seconds have strong appeal: a hook, conflict, curiosity, a sharp statement, emotion, or an implicit question.
- An ideal clip has this structure:
  hook -> brief context -> tension/insight -> payoff.
- Don't pick a clip that only gets interesting after running for too long.
- If the beginning of a segment is too slow, shift start_time to a stronger sentence.
- If the payoff is already done, don't extend the clip further without reason.
- Don't include intros, small talk, long pauses, or transitions that don't add appeal.
- Prioritize clips that make viewers want to:
  1. stop scrolling,
  2. watch to the end,
  3. comment,
  4. share,
  5. save,
  6. or feel "this is so me".

TIMING-CUT RULES:
- start_time must begin as close as possible to the first strong moment, not just the start of a topic.
- end_time must stop after the payoff, conclusion, punchline, or main emotional beat is finished.
- Don't cut too early if a sentence is still hanging.
- Don't continue the clip too long after the core message is done.
- The clip must remain understandable without watching the parts before or after it.
- If two strong moments are very close together and reinforce each other, they may be merged as long as duration stays within {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds.
- If two strong moments have different angles, separate them as different clip candidates.

INTERNAL VIRAL_SCORE ASSESSMENT:
Score viral_score 1-100 based on the following components. This is for internal scoring only, DO NOT add a new field to the JSON.
- Hook strength: 1-20
- Emotional intensity: 1-20
- Shareability/comment potential: 1-20
- Standalone clarity: 1-20
- Payoff/retention: 1-20

Scoring guide (with score anchors):
- Hook strength: how strongly the first 2-3 seconds make someone stop scrolling.
  20=the first sentence is immediately a curiosity gap/bold claim/specific number. 10=engaging enough but needs context. 1=generic, no reason to stop scrolling.
- Emotional intensity: how strong the emotion, conflict, unease, humor, warmth, anger, awe, or relatability is.
  20=instant, strong emotional reaction. 10=some emotion but mild. 1=flat/informational with no emotional charge.
- Shareability/comment potential: how likely people are to comment, debate, tag a friend, share, or save.
  20=controversial/quotable opinion, immediately provokes replies/debate. 10=engaging but doesn't provoke a strong reaction. 1=no reason to interact.
- Standalone clarity: how easily the clip is understood without the full video's context.
  20=100% stands alone, needs no outside info. 10=needs a little assumption. 1=confusing without the full video's context.
- Payoff/retention: how clear the reward for watching to the end is — punchline, insight, twist, conclusion, or practical takeaway.
  20=clear, satisfying payoff at the end. 10=has a conclusion but weak. 1=clip stops without a clear resolution.
- Don't pick a clip with viral_score below 70 unless the number of good moments in the transcript is very limited.

TARGET ACCOUNT CLASSIFICATION (FOR EACH CLIP):
Determine the target account based on the clip's ANGLE. Don't judge by topic alone (e.g. beauty doesn't automatically go to Life). Judge by angle:
{_build_account_classification_prompt()}

SPECIAL CLASSIFICATION RULES:
1. Finance doesn't automatically fall into one category. (Economic theory/financial history explained informatively -> Knowledge. Practical investment/personal-finance advice -> GrowthAndMoney. Technical tutorial, e.g. "how to use Excel for budgeting" -> SkillsAndLifestyle).
2. Psychology/self-help is split by angle. (Explaining a psychology concept/research informatively -> Knowledge. Concrete action advice for changing habits/life -> GrowthAndMoney).
3. Science/history packaged as a "how-to" (e.g. a science experiment viewers can try themselves) -> SkillsAndLifestyle, not Knowledge.

HOOK (REQUIRED):
- Take 1 punchy sentence that EXISTS INSIDE the clip — pick the sentence closest to one of these patterns:
  - A question that immediately triggers curiosity.
  - A bold/surprising statement made early on.
  - A specific number or claim that contrasts with common expectation.
  - A sentence that directly touches the viewer's problem/anxiety ("if you've ever felt...").
- The hook must feel strong and attention-grabbing within the first ~{durasi_hook} seconds.
- Save as hook_start_time and hook_end_time.
- The hook must make people want to keep watching, but no fake clickbait — whatever the hook promises must actually be covered in the clip.
- Make sure the hook is natural and genuinely spoken in the transcript.
- If the best hook isn't right at the start of the clip candidate, adjust start_time so the hook appears as early as possible.
- The hook must work as opening on-screen text to hold viewers in the first 2-3 seconds.

TYPOGRAPHY PLAN (KINETIC TYPOGRAPHY):
- Pick 3-6 SINGLE words that are the most weighty, emotional, or most worth emphasizing from each clip.
- For each word, determine:
  1. 'kata_utama': the specific word, spelled exactly as it appears in the transcript.
  2. 'scale_level': pick 1, 2, or 3.
     - 1 = normal/small
     - 2 = large/emphasis
     - 3 = huge/very crucial
  3. 'style': pick "utama" or "khusus".
  4. 'animasi': pick "bounce_pop" or "stagger_up".
- Don't pick long phrases. Single words only.
- Prioritize the word that's strongest emotionally, in meaning, or for visual retention.

B-ROLL (REQUIRED IF RELEVANT):
- Find up to 1-3 moments in the clip that are a great fit for B-roll / stock footage.
- Each B-roll is 3-7 seconds long.
- Provide:
  - start_time
  - end_time
  - search_query
- search_query must be short, clear, and in English.
- Don't place B-roll at the exact same second as the hook.
- Only add B-roll if it genuinely helps visualize what's being said.
- If no moment fits, fill broll_list with an empty array [].

VISUAL B-ROLL HOOK (FIRST 0-3 SECONDS):
- Provide 2-5 opening B-Roll ideas that are contrasting, funny, dramatic, or curiosity-provoking before the original footage comes in.
- Include YouTube/TikTok search keywords for the editor.
- If there's a gesture that could work as a visual hook, give that reference too.
- This is stored in the 'recommended_visual_broll_hook' object and only serves as a reference if the editor wants to manually source footage for the first 3 seconds.

BGM MOOD (BACKGROUND MUSIC):
- Analyze this clip's emotion and topic.
- Pick ONE background-music mood that fits best from this fixed list: [chill, epic, sad, upbeat, suspense].
- Make sure the mood matches the story. (Example: a hard-struggle story = sad/epic, a funny/relaxed story = chill/upbeat).

SLOW CLOSING:
- end_time MUST have +0.10 to +0.85 seconds of padding added after the last word so the ending feels relaxed and doesn't cut off abruptly.

SELECTION REASONING:
- Fill the 'alasan' field with a brief explanation of why this clip deserves to be picked.
- Focus on emotional value, hook strength, retention potential, shareability, and payoff.
- Explain the clip's main viral trigger.
- Explain why people are likely to watch to the end.
- Explain why the clip stays interesting even watched without the full video's context.

METADATA LANGUAGE RULES:
- title_indonesia is still required for internal compatibility / fallback.
- title_indonesia MUST be in natural Indonesian, max 100 characters.
- All main cross-platform metadata must be in natural English.
- This applies to:
  - title_inggris
  - hastag
  - description_hook
  - description_context
  - keyword_tags
  - tiktok_caption
- Specifically for Indonesian TikTok needs, also create:
  - tiktok_title_id
  - tiktok_caption_id
- tiktok_title_id and tiktok_caption_id MUST be in natural Indonesian.
- tiktok_title_id must be more descriptive than title_indonesia, may be longer than 100 characters if needed, and must clearly explain the clip/video's content.
- tiktok_caption_id must be natural, informative, fit for an Indonesian audience, and may be a bit longer if it helps explain the clip's content.
- Don't mix Indonesian and English within the same field.
- Use natural, concise, easy-to-read English suited for short-form content.
- Avoid stiff, literal translations.

CROSS-PLATFORM METADATA:
For each clip, produce the following metadata:

1. title_indonesia
- Natural Indonesian, short, and relevant.
- This is only for internal compatibility / fallback.
- Max 100 characters.

2. title_inggris
- Natural English, strong, sharp, and easy to read.
- This is the main title for platform metadata.
- Max 100 characters.
- Focus on 1 main idea.
- Relevant to the clip's content, not the full video's content in general.
- No cheap clickbait.
- No excessive capitalization.
- Avoid excessive punctuation like !!! ??? ...
- Not too generic.

3. hastag
- Fill with 5 to 8 hashtags in one string.
- All hashtags MUST be in English.
- Separate with spaces.
- Mix hashtag types for maximum reach:
  - 1-2 broad/high-traffic tags (e.g. #fyp #viral) — only if they genuinely fit the content, don't force them.
  - 2-3 niche/topic-specific tags directly tied to the clip's subject.
  - 2-3 long-tail/community tags that reach a smaller but highly relevant audience (e.g. #podcastclips, #mindsettips).
- No duplicates.
- Every hashtag must still make sense for this specific clip — don't stuff irrelevant trending tags just for reach.
- Use a format like: #mindset #productivitytips #careeradvice #growthmindset #podcastclips

4. description_hook
- Exactly 1 sentence.
- MUST be in English.
- This is the metadata's opening sentence.
- Must be short, strong, and curiosity-provoking.
- No fake clickbait.

5. description_context
- Exactly 1 sentence.
- MUST be in English.
- Briefly explains the clip's main context.
- Must be relevant to what's discussed in the clip.

6. keyword_tags
- Contains 5 to 8 short keywords.
- MUST be in English.
- Not hashtags.
- Must be a list of short phrases relevant to the clip's content.
- Avoid keyword spam.
- Prioritize keywords people might actually search for.
- This field is mainly for YouTube metadata needs.

7. tiktok_title_id
- Natural Indonesian.
- Longer and more descriptive of the video's content than title_indonesia.
- No 100-character limit, but still must be concise, clear, and easy to read.
- Must be relevant to the clip's content, not the full long video's content in general.
- No cheap clickbait.

8. tiktok_caption_id
- 1 to 2 sentences.
- MUST be in Indonesian.
- May be a bit longer than the English caption if it helps explain the clip's content.
- Natural, light, easy-to-read style.
- Stay true to the clip's content.
- Don't just copy-paste the title.
- Not too formal.

9. tiktok_caption
- 1 to 2 short sentences.
- MUST be in English.
- More natural, light, conversational style.
- Stay true to the clip's content.
- Don't just copy-paste the title.
- Not too formal.
- Try to keep it under 140 characters.

METADATA QUALITY RULES:
- All metadata must match the clip's content, not the full long video's content in general.
- Don't make promises that aren't covered in the clip.
- Don't use fake hyperbole like "100% works", "guaranteed to make you rich", etc. unless it's genuinely and clearly stated.
- If there are numbers, strong phrases, or sharp statements from the original speech, prioritize those as title/caption inspiration.
- Title, descriptions, and caption must complement each other, not repeat the same sentence.
- All metadata fields used for platforms must be in natural English, not a stiff literal translation.
- For tiktok_title_id and tiktok_caption_id specifically, use natural, clear Indonesian that better explains the clip's content for an Indonesian audience.

OUTPUT RULES:
- Output MUST be a valid JSON array.
- Don't give any explanation outside the JSON.
- All fields are required.
- If in doubt, prioritize accuracy to the clip's content over excessive creativity.
{_hook_v2_prompt}{_segment_prompt}

REQUIRED JSON STRUCTURE (follow these field names exactly):
[
  {{
    "rank": 1,
    "viral_score": 95,
    "start_time": 30.5,
    "end_time": 90.0,
    "hook_start_time": 30.5,
    "hook_end_time": 35.0,
    "bgm_mood": "mood_here",
    "typography_plan": [{{ "kata_utama": "...", "scale_level": 2, "style": "utama", "animasi": "bounce_pop" }}],
    "broll_list": [{{ "start_time": 40.0, "end_time": 45.0, "search_query": "..." }}],
    "recommended_visual_broll_hook": [
      {{ "broll_idea": "...", "search_keyword": "...", "why_it_works": "..." }}
    ],
    "hook_v2": {{
      "enabled": true,
      "items": [{{ "start_time": 31.0, "end_time": 32.5, "text": "KEYWORD" }}],
      "transition": {{ "type": "white_flash" }}
    }},
    "keep_segments": [
      {{ "start_time": 30.5, "end_time": 55.0 }},
      {{ "start_time": 58.0, "end_time": 90.0 }}
    ],
    "title_indonesia": "...",
    "title_inggris": "...",
    "hastag": "#hastag1 #hastag2",
    "description_hook": "...",
    "description_context": "...",
    "keyword_tags": ["tag1", "tag2"],
    "tiktok_title_id": "...",
    "tiktok_caption_id": "...",
    "tiktok_caption": "...",
    "alasan": "...",
    "klasifikasi_akun": {{
      "tipe_akun": "Knowledge",
      "akun_tujuan": "Knowledge.Clips",
      "confidence": 87,
      "angle_utama": "Informative history/science explanation",
      "alasan": "...",
      "kata_kunci_pendukung": ["history", "science"],
      "bio_akun": "...",
      "alternatif_akun": {{
        "tipe_akun": "GrowthAndMoney",
        "akun_tujuan": "Growth.Clips",
        "alasan": "..."
      }}
    }}
  }}
]

Transcript:
{transkrip_lengkap}
"""


def _build_clips_schema() -> dict:
    """JSON Schema for one array item this prompt asks for — shared by any provider that
    supports schema-constrained decoding. Originally built for NVIDIA NIM's nvext.guided_json
    (since removed — that field isn't recognized by current NIM models), reused here for
    Groq's standard OpenAI-compatible response_format={"type": "json_schema", ...} strict mode,
    which is exactly the lever that makes a small model (e.g. openai/gpt-oss-20b) reliably
    produce this schema's many required fields instead of just being asked nicely in the prompt."""
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "rank": {"type": "integer"},
                "viral_score": {"type": "integer"},
                "start_time": {"type": "number"},
                "end_time": {"type": "number"},
                "hook_start_time": {"type": "number"},
                "hook_end_time": {"type": "number"},
                "bgm_mood": {
                    "type": "string",
                    "enum": ["chill", "epic", "sad", "upbeat", "suspense"]
                },
                "typography_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kata_utama": {"type": "string"},
                            "scale_level": {"type": "integer", "enum": [1, 2, 3]},
                            "style": {"type": "string", "enum": ["utama", "khusus"]},
                            "animasi": {"type": "string", "enum": ["bounce_pop", "stagger_up"]}
                        },
                        "required": ["kata_utama", "scale_level", "style", "animasi"]
                    }
                },
                "broll_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                            "search_query": {"type": "string"}
                        },
                        "required": ["start_time", "end_time", "search_query"]
                    }
                },
                "recommended_visual_broll_hook": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "broll_idea": {"type": "string"},
                            "search_keyword": {"type": "string"},
                            "why_it_works": {"type": "string"}
                        },
                        "required": ["broll_idea", "search_keyword", "why_it_works"]
                    }
                },
                "title_indonesia": {"type": "string"},
                "title_inggris": {"type": "string"},
                "hastag": {"type": "string"},
                "description_hook": {"type": "string"},
                "description_context": {"type": "string"},
                "keyword_tags": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "tiktok_title_id": {"type": "string"},
                "tiktok_caption_id": {"type": "string"},
                "tiktok_caption": {"type": "string"},
                "alasan": {"type": "string"},
                "klasifikasi_akun": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tipe_akun": {"type": "string", "enum": list(TARGET_ACCOUNTS.keys())},
                        "akun_tujuan": {"type": "string"},
                        "confidence": {"type": "integer"},
                        "angle_utama": {"type": "string"},
                        "alasan": {"type": "string"},
                        "kata_kunci_pendukung": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "bio_akun": {"type": "string"},
                        "alternatif_akun": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tipe_akun": {"type": "string", "enum": list(TARGET_ACCOUNTS.keys())},
                                "akun_tujuan": {"type": "string"},
                                "alasan": {"type": "string"}
                            },
                            "required": ["tipe_akun", "akun_tujuan", "alasan"]
                        }
                    },
                    "required": ["tipe_akun", "akun_tujuan", "confidence", "angle_utama", "alasan", "kata_kunci_pendukung", "bio_akun", "alternatif_akun"]
                },
                "hook_v2": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "start_time": {"type": "number"},
                                    "end_time": {"type": "number"},
                                    "text": {"type": "string"},
                                },
                                "required": ["start_time", "end_time", "text"],
                            },
                        },
                        "transition": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "enum": ["white_flash", "glitch"]},
                            },
                            "required": ["type"],
                        },
                    },
                    "required": ["enabled", "items", "transition"],
                },
                "keep_segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                        },
                        "required": ["start_time", "end_time"],
                    },
                },
            },
            "required": [
                "rank", "viral_score", "start_time", "end_time", "hook_start_time", "hook_end_time",
                "bgm_mood", "typography_plan", "broll_list", "recommended_visual_broll_hook", "title_indonesia",
                "title_inggris", "hastag", "description_hook", "description_context",
                "keyword_tags", "tiktok_title_id", "tiktok_caption_id", "tiktok_caption",
                "alasan", "klasifikasi_akun", "hook_v2", "keep_segments"
            ]
        }
    }


def analyze_with_nvidia(transkrip_lengkap: str, cfg) -> list[dict]:
    """Analyze transcript using NVIDIA NIM API (OpenAI compatible)."""
    from openai import OpenAI
    
    print(f"[3/3] Menganalisis Top {cfg.jumlah_clip} momen menggunakan NVIDIA ({cfg.nvidia_model})...")
    
    if not cfg.api_key_nvidia:
        raise ValueError("NVIDIA_API_KEY tidak ditemukan di environment.")

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=cfg.api_key_nvidia
    )
    
    prompt = get_analysis_prompt(transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)

    last_exc = None
    completion = None
    for attempt in range(1, NVIDIA_MAX_ATTEMPTS + 1):
        try:
            print(f"[NVIDIA] Attempt {attempt}/{NVIDIA_MAX_ATTEMPTS}...")
            completion = client.chat.completions.create(
                model=cfg.nvidia_model,
                messages=[
                    {"role": "system", "content": "You are a professional video editor and strategist. Return JSON only. Follow the provided JSON schema exactly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                top_p=1,
                max_tokens=16384,
                extra_body={
                    "chat_template_kwargs": {"thinking": False},
                }
            )
            break
        except Exception as exc:
            last_exc = exc
            print(f"[NVIDIA] Attempt {attempt}/{NVIDIA_MAX_ATTEMPTS} gagal | error={exc}")
            if attempt == NVIDIA_MAX_ATTEMPTS:
                raise
            wait_seconds = NVIDIA_INITIAL_WAIT_SECONDS + ((attempt - 1) * NVIDIA_WAIT_INCREMENT_SECONDS)
            print(f"[NVIDIA] Retry lagi dalam {wait_seconds} detik...")
            time.sleep(wait_seconds)

    content = completion.choices[0].message.content
    
    if "```" in content:
        content = re.sub(r"```(json)?", "", content).strip()
        content = content.split("```")[0].strip()
        
    hasil = json.loads(content)
    
    # Guided JSON should return an array directly if schema says type: array
    # but we keep the unwrapper just in case of non-conforming fallbacks
    if isinstance(hasil, dict):
        for key in ["clips", "data", "highlights"]:
            if key in hasil and isinstance(hasil[key], list):
                hasil = hasil[key]
                break
                
    if not isinstance(hasil, list):
        if isinstance(hasil, dict):
            return [hasil]
        raise ValueError(f"Provider NVIDIA mengembalikan format non-list/dict: {type(hasil)}")

    return hasil


def analyze_with_groq(transkrip_lengkap: str, cfg) -> list[dict]:
    """Analyze transcript using Groq's API (OpenAI compatible, LPU-hosted for speed)."""
    from openai import OpenAI

    print(f"[3/3] Menganalisis Top {cfg.jumlah_clip} momen menggunakan Groq ({cfg.groq_model})...")

    if not cfg.api_key_groq:
        raise ValueError("GROQ_API_KEY tidak ditemukan di environment.")

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=cfg.api_key_groq,
    )

    prompt = get_analysis_prompt(transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)

    # Strict schema-constrained decoding — only some Groq models support it (per
    # console.groq.com/docs/structured-outputs). This is the actual lever for making a
    # smaller model reliably produce this prompt's many required fields: the model is
    # physically prevented from emitting anything that doesn't match the schema, rather
    # than just being asked nicely in the prompt text. Falls back to loose json_object
    # mode (best-effort, relies on the prompt + our own unwrapping/parsing) for any
    # model outside that support list.
    STRICT_SCHEMA_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"}
    if cfg.groq_model in STRICT_SCHEMA_MODELS:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "clips_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"clips": _build_clips_schema()},
                    "required": ["clips"],
                },
            },
        }
    else:
        response_format = {"type": "json_object"}

    last_exc = None
    completion = None
    for attempt in range(1, NVIDIA_MAX_ATTEMPTS + 1):
        try:
            print(f"[Groq] Attempt {attempt}/{NVIDIA_MAX_ATTEMPTS}...")
            completion = client.chat.completions.create(
                model=cfg.groq_model,
                messages=[
                    {"role": "system", "content": "You are a professional video editor and strategist. Return JSON only. Follow the provided JSON schema exactly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                top_p=1,
                # Groq's free-tier TPM limit is small (e.g. 8,000 for gpt-oss-20b) and counts
                # max_tokens as reserved headroom against that budget upfront, not just actual
                # output length — 16384 (borrowed from the NVIDIA path, which has no such limit)
                # was blowing the request over the cap before the model even ran. The real output
                # here is a small JSON object, not a long document.
                max_tokens=3072,
                response_format=response_format,
            )
            break
        except Exception as exc:
            last_exc = exc
            print(f"[Groq] Attempt {attempt}/{NVIDIA_MAX_ATTEMPTS} gagal | error={exc}")
            if attempt == NVIDIA_MAX_ATTEMPTS:
                raise
            wait_seconds = NVIDIA_INITIAL_WAIT_SECONDS + ((attempt - 1) * NVIDIA_WAIT_INCREMENT_SECONDS)
            print(f"[Groq] Retry lagi dalam {wait_seconds} detik...")
            time.sleep(wait_seconds)

    content = completion.choices[0].message.content

    if "```" in content:
        content = re.sub(r"```(json)?", "", content).strip()
        content = content.split("```")[0].strip()

    hasil = json.loads(content)

    if isinstance(hasil, dict):
        for key in ["clips", "data", "highlights"]:
            if key in hasil and isinstance(hasil[key], list):
                hasil = hasil[key]
                break

    if not isinstance(hasil, list):
        if isinstance(hasil, dict):
            return [hasil]
        raise ValueError(f"Provider Groq mengembalikan format non-list/dict: {type(hasil)}")

    return hasil


_TRANSCRIPT_TIMESTAMP_RE = re.compile(r"\[\s*[\d.]+\s*-\s*([\d.]+)\s*\]")


def _estimate_transcript_duration_seconds(transkrip_lengkap: str) -> float:
    """Reads the source video's duration back out of the transcript's own
    "[start - end] text" line format (see get_analysis_prompt's format description) —
    the last end-timestamp found is the video length. Returns 0.0 if unparseable, which
    callers should treat as "unknown, don't gate on it" rather than "zero-length video"."""
    matches = _TRANSCRIPT_TIMESTAMP_RE.findall(transkrip_lengkap)
    if not matches:
        return 0.0
    try:
        return max(float(m) for m in matches)
    except ValueError:
        return 0.0


def analyze_with_ai(transkrip_lengkap: str, cfg) -> list[dict]:
    """Dispatcher for AI analysis based on provider."""
    provider = getattr(cfg, "ai_provider", "gemini")

    if provider == "nvidia":
        if not cfg.api_key_nvidia:
            print("⚠️ NVIDIA_API_KEY tidak ditemukan! Mencoba fallback ke Gemini...")
        else:
            try:
                return analyze_with_nvidia(transkrip_lengkap, cfg)
            except Exception as e:
                print(f"⚠️ NVIDIA API gagal: {e}. Fallback ke Gemini...")

    if provider == "groq":
        from .config import GROQ_MAX_VIDEO_DURATION_SECONDS  # local import: only needed here,
        # and avoids relying on cfg.groq_max_duration_seconds always being set (it is, via
        # build_config(), but this getattr fallback is the defensive case where it isn't).
        max_duration = getattr(cfg, "groq_max_duration_seconds", GROQ_MAX_VIDEO_DURATION_SECONDS)
        video_duration = _estimate_transcript_duration_seconds(transkrip_lengkap) if max_duration else 0.0
        oversized = bool(max_duration) and video_duration > max_duration

        if not cfg.api_key_groq:
            print("⚠️ GROQ_API_KEY tidak ditemukan! Mencoba fallback ke Gemini...")
        elif oversized and not getattr(cfg, "groq_oversized_fallback_gemini", False):
            raise RuntimeError(
                f"Video ini {video_duration/60:.1f}min, melebihi --groq-max-duration-seconds "
                f"({max_duration/60:.1f}min) — transkrip penuh akan melebihi TPM budget Groq's "
                f"free tier. Dilewati (bukan fallback ke Gemini — pass "
                f"--groq-oversized-fallback-gemini untuk mengubah perilaku ini)."
            )
        elif oversized:
            print(
                f"⚠️ Video ini {video_duration/60:.1f}min, melebihi --groq-max-duration-seconds "
                f"({max_duration/60:.1f}min) — transkrip penuh akan melebihi TPM budget Groq's "
                f"free tier. Melewati Groq, langsung ke Gemini..."
            )
        else:
            try:
                return analyze_with_groq(transkrip_lengkap, cfg)
            except Exception as e:
                print(f"⚠️ Groq API gagal: {e}. Fallback ke Gemini...")

    return analyze_with_gemini(transkrip_lengkap, cfg)


def analyze_with_gemini(
    transkrip_lengkap: str,
    cfg,
) -> list[dict]:
    """Analyse transcript with Gemini AI."""
    import google.genai as genai
    from google.genai import types

    print(f"[3/3] Menganalisis Top {cfg.jumlah_clip} momen terbaik menggunakan Gemini...")

    prompt = get_analysis_prompt(transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)

    # JSON Schema definitions (same as before)
    schema_broll = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "start_time": {"type": "NUMBER"},
                "end_time": {"type": "NUMBER"},
                "search_query": {"type": "STRING"},
            },
            "required": ["start_time", "end_time", "search_query"],
        },
    }

    schema_visual_broll_hook = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "broll_idea": {"type": "STRING"},
                "search_keyword": {"type": "STRING"},
                "why_it_works": {"type": "STRING"},
            },
            "required": ["broll_idea", "search_keyword", "why_it_works"],
        },
    }

    schema_typography = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "kata_utama": {"type": "STRING"},
                "scale_level": {"type": "INTEGER"},
                "style": {"type": "STRING"},
                "animasi": {"type": "STRING"},
            },
            "required": ["kata_utama", "scale_level", "style", "animasi"],
        },
    }

    schema_klasifikasi = {
        "type": "OBJECT",
        "properties": {
            "tipe_akun": {"type": "STRING"},
            "akun_tujuan": {"type": "STRING"},
            "confidence": {"type": "INTEGER"},
            "angle_utama": {"type": "STRING"},
            "alasan": {"type": "STRING"},
            "kata_kunci_pendukung": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "bio_akun": {"type": "STRING"},
            "alternatif_akun": {
                "type": "OBJECT",
                "properties": {
                    "tipe_akun": {"type": "STRING"},
                    "akun_tujuan": {"type": "STRING"},
                    "alasan": {"type": "STRING"},
                },
                "required": ["tipe_akun", "akun_tujuan", "alasan"],
            },
        },
        "required": ["tipe_akun", "akun_tujuan", "confidence", "angle_utama", "alasan", "kata_kunci_pendukung", "bio_akun", "alternatif_akun"],
    }

    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    gemini_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "rank": {"type": "INTEGER"},
                    "viral_score": {"type": "INTEGER"},
                    "hook_start_time": {"type": "NUMBER"},
                    "hook_end_time": {"type": "NUMBER"},
                    "start_time": {"type": "NUMBER"},
                    "end_time": {"type": "NUMBER"},
                    "typography_plan": schema_typography,
                    "broll_list": schema_broll,
                    "recommended_visual_broll_hook": schema_visual_broll_hook,
                    "alasan": {"type": "STRING"},
                    "bgm_mood": {"type": "STRING"},
                    "title_indonesia": {"type": "STRING"},
                    "title_inggris": {"type": "STRING"},
                    "hastag": {"type": "STRING"},
                    "description_hook": {"type": "STRING"},
                    "description_context": {"type": "STRING"},
                    "keyword_tags": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "tiktok_title_id": {"type": "STRING"},
                    "tiktok_caption_id": {"type": "STRING"},
                    "tiktok_caption": {"type": "STRING"},
                    "klasifikasi_akun": schema_klasifikasi,
                    "hook_v2": {
                        "type": "OBJECT",
                        "properties": {
                            "enabled": {"type": "BOOLEAN"},
                            "items": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "start_time": {"type": "NUMBER"},
                                        "end_time": {"type": "NUMBER"},
                                        "text": {"type": "STRING"},
                                    },
                                    "required": ["start_time", "end_time", "text"],
                                },
                            },
                            "transition": {
                                "type": "OBJECT",
                                "properties": {
                                    "type": {"type": "STRING"},
                                },
                                "required": ["type"],
                            },
                        },
                        "required": ["enabled", "items", "transition"],
                    },
                    "keep_segments": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start_time": {"type": "NUMBER"},
                                "end_time": {"type": "NUMBER"},
                            },
                            "required": ["start_time", "end_time"],
                        },
                    },
                },
                "required": [
                    "rank", "viral_score", "hook_start_time", "hook_end_time",
                    "start_time", "end_time", "typography_plan",
                    "broll_list", "recommended_visual_broll_hook", "alasan", "bgm_mood",
                    "title_indonesia", "title_inggris", "hastag",
                    "description_hook", "description_context",
                    "keyword_tags", "tiktok_title_id",
                    "tiktok_caption_id", "tiktok_caption",
                    "klasifikasi_akun", "hook_v2", "keep_segments",
                ],
            },
        },
    )

    return _generate_json_with_retry(
        client=client,
        model=cfg.gemini_model,
        fallback_model=getattr(cfg, "gemini_fallback_model", None),
        contents=prompt,
        config=gemini_config,
    )
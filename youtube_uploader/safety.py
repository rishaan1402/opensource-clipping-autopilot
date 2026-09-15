"""
youtube_uploader.safety — Daily limits, queue limits, and manual approval.

Restored from youtube_uploader/Safety.md, which documents that this module
was deliberately removed at some point "agar uploader berjalan 100% secara
otomatis" (so the uploader runs 100% automatically) — but the code was kept
there specifically as a "bring this back if you want it" reference, and
run_upload.py was left calling it, unfixed, ever since.

Restored rather than left removed because it's the same review-gate
philosophy the rest of this pipeline now uses elsewhere (clipping.rights,
clipping.channel_trust): fast and automatic where a machine-checkable fact
already makes the decision safe, with a cheap human checkpoint kept exactly
where judgment — not a rule — is what's actually being relied on. A daily
upload cap and a one-line approval prompt cost almost nothing and are the
last line of defense against a scoring bug or a bad clip silently going out
uncorrected in a fully automated run.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo


def _get_tz(tz_name: str):
    # zoneinfo, not pytz — matches youtube_uploader/uploader.py's own
    # timezone handling rather than adding a second timezone dependency.
    return ZoneInfo(tz_name)


def load_safety_config(config_path: str = "upload_safety.json") -> dict:
    default_config = {
        "max_upload_per_day": 3,
        "max_upload_per_run": 2,
        "interval_hours_min": 2,
        "max_scheduled_queue": 15,
        "require_manual_approval": True,
        "upload_log_file": "upload_history.json"
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                default_config.update(user_cfg)
        except Exception as e:
            print(f"⚠️ Gagal membaca {config_path}: {e}")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4)

    return default_config


def load_upload_history(log_file: str) -> list:
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_upload_history(log_file: str, history: list):
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4)


def record_upload(log_file: str, video_id: str, title: str, tz_name: str = "Asia/Makassar"):
    history = load_upload_history(log_file)
    tz = _get_tz(tz_name)
    now = datetime.now(tz)

    history.append({
        "video_id": video_id,
        "title": title,
        "uploaded_at": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "date": now.strftime("%Y-%m-%d"),
    })
    save_upload_history(log_file, history)


def count_uploads_today(log_file: str, tz_name: str = "Asia/Makassar") -> int:
    history = load_upload_history(log_file)
    tz = _get_tz(tz_name)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    return sum(1 for entry in history if entry.get("date") == today_str)


def check_daily_limit(safety_config: dict, tz_name: str = "Asia/Makassar") -> tuple[bool, int, int]:
    log_file = safety_config["upload_log_file"]
    max_per_day = safety_config["max_upload_per_day"]
    uploads_today = count_uploads_today(log_file, tz_name)
    return uploads_today < max_per_day, uploads_today, max_per_day


def enforce_min_interval(requested_hours: int, safety_config: dict) -> int:
    min_hours = safety_config["interval_hours_min"]
    effective = max(requested_hours, min_hours)
    if effective != requested_hours:
        print(f"🛡️ Interval diubah dari {requested_hours}h → {effective}h")
    return effective


def limit_pending_items(items: list, safety_config: dict) -> list:
    max_per_run = safety_config["max_upload_per_run"]
    if len(items) > max_per_run:
        print(f"🛡️ Membatasi upload: {len(items)} item → {max_per_run} item per run")
        return items[:max_per_run]
    return items


def check_queue_limit(youtube, safety_config: dict, tz_name: str = "Asia/Makassar") -> tuple[bool, int, int]:
    from .uploader import get_latest_scheduled_publish_time, parse_rfc3339_to_local
    max_queue = safety_config["max_scheduled_queue"]
    try:
        tz = _get_tz(tz_name)
        now_local = datetime.now(tz)
        channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
        channel_items = channel_resp.get("items", [])
        if not channel_items:
            return True, 0, max_queue

        uploads_playlist_id = channel_items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads_playlist_id:
            return True, 0, max_queue

        scheduled_count = 0
        page_token = None
        for _ in range(5):
            playlist_resp = youtube.playlistItems().list(
                part="contentDetails", playlistId=uploads_playlist_id, maxResults=50, pageToken=page_token
            ).execute()
            playlist_items = playlist_resp.get("items", [])
            if not playlist_items:
                break

            video_ids = [row.get("contentDetails", {}).get("videoId") for row in playlist_items if row.get("contentDetails", {}).get("videoId")]
            if video_ids:
                videos_resp = youtube.videos().list(part="status", id=",".join(video_ids), maxResults=50).execute()
                for video in videos_resp.get("items", []):
                    status = video.get("status", {})
                    publish_at = status.get("publishAt")
                    privacy = status.get("privacyStatus")
                    if not publish_at or privacy != "private":
                        continue

                    dt_local = parse_rfc3339_to_local(publish_at, tz_name)
                    if dt_local and dt_local > now_local:
                        scheduled_count += 1

            page_token = playlist_resp.get("nextPageToken")
            if not page_token:
                break

        return scheduled_count < max_queue, scheduled_count, max_queue
    except Exception as e:
        print(f"⚠️ Gagal mengecek scheduled queue: {e}")
        return True, 0, max_queue


def prompt_manual_approval(item: dict, publish_at_local=None) -> bool:
    title = item.get("youtube_title_final") or item.get("title_inggris") or f"Clip Rank {item.get('rank', '?')}"
    video_path = item.get("video_path", "?")

    print("\n" + "=" * 60)
    print("🛡️ MANUAL APPROVAL REQUIRED")
    print("=" * 60)
    print(f"  Judul    : {title}")
    print(f"  File     : {os.path.basename(video_path)}")
    if publish_at_local:
        print(f"  Jadwal   : {publish_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 60)
    print()
    print("⚠️  CHECKLIST SEBELUM APPROVE:")
    print("  □ Sudah review video secara manual?")
    print("  □ Ada narasi/analisis/voice-over kamu sendiri?")
    print("  □ Judul & thumbnail BUKAN meniru creator asli?")
    print()

    while True:
        try:
            answer = input("Upload video ini? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n⏹️ Upload dibatalkan oleh user.")
            return False

        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            print("⏭️ Video dilewati.")
            return False
        print("   Ketik 'y' untuk upload atau 'n' untuk skip.")


def print_safety_summary(safety_config: dict, tz_name: str = "Asia/Makassar") -> None:
    is_allowed, uploads_today, max_per_day = check_daily_limit(safety_config, tz_name)
    print("\n" + "=" * 60)
    print("🛡️ UPLOAD SAFETY RULES")
    print("=" * 60)
    print(f"  Max per run        : {safety_config['max_upload_per_run']}")
    print(f"  Max per day        : {max_per_day} (today: {uploads_today})")
    print(f"  Min interval       : {safety_config['interval_hours_min']}h")
    print(f"  Max scheduled queue: {safety_config['max_scheduled_queue']}")
    print(f"  Manual approval    : {'ON ✅' if safety_config['require_manual_approval'] else 'OFF ⚠️'}")
    print(f"  Upload log         : {safety_config['upload_log_file']}")
    print("=" * 60)
    if not is_allowed:
        print(f"\n🚫 DAILY LIMIT REACHED! Sudah {uploads_today}/{max_per_day} upload hari ini.")

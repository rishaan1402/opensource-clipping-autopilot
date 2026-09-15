#!/usr/bin/env python3
"""
discover_new_clips.py — Poll approved CC channels for new uploads, then clip them.

Closes the actual gap found after building the rights gate: everything from
"here's a URL" onward is automated (autopilot.py), but getting the URL in
the first place was still 100% manual. This polls the channels already
approved via `python -m clipping.channel_trust approve <channel_id>`, finds
videos not yet processed (clipping.phase1.deduplication — the same store
the main pipeline already writes to), re-verifies each one's license fresh
(a license can change between approval and now), and hands qualifying ones
to autopilot.py — one subprocess per video, so one bad video can't take
down the whole run.

Usage:
    # See what would run, without actually running it
    python discover_new_clips.py --dry-run

    # Process up to 3 new videos, clip only (no upload)
    python discover_new_clips.py --max-new 3

    # Process up to 3 new videos and publish to YouTube (manual-approval
    # prompt from youtube_uploader/safety.py still applies unless you also
    # pass --youtube-no-approval through)
    python discover_new_clips.py --max-new 3 --upload-youtube

Meant to be run on a schedule (cron/launchd/Task Scheduler) once a few
manual runs show it's picking sensible videos.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from itertools import zip_longest

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from clipping import channel_trust
from clipping.phase1.deduplication import DeduplicationManager
from clipping.phase1.input_handler import InputSource
from cc_supply_probe import fetch_video_details, _parse_iso8601_duration


def find_new_candidates(
    api_key: str, trust_db_path: str, dedup_dir: str, min_duration: float, per_channel_sample: int = 50
) -> list[dict]:
    """
    Returns new, license-re-verified, long-enough candidates from approved
    channels — interleaved round-robin across channels (one from channel A,
    one from B, one from C, then back to A...) rather than exhausting
    whichever channel happens to sort first. A single prolific channel
    (a city council streaming every meeting, say) would otherwise fill an
    entire --max-new cap before any other approved channel got a look in.
    """
    dedup = DeduplicationManager(dedup_dir)
    approved = channel_trust.list_by_review_status(trust_db_path, channel_trust.REVIEW_APPROVED)
    print(f"📡 Polling {len(approved)} approved channels for new uploads...")

    per_channel: list[list[dict]] = []
    for ch in approved:
        try:
            uploads_playlist_id = channel_trust._get_uploads_playlist_id(api_key, ch["channel_id"])
            if not uploads_playlist_id:
                continue
            recent_ids = channel_trust._get_recent_video_ids(api_key, uploads_playlist_id, per_channel_sample)
        except Exception as e:
            print(f"   ⚠️  {ch['channel_name']}: poll failed ({e})")
            continue

        new_ids = [
            vid for vid in recent_ids
            if dedup.check_video_duplicate(InputSource(source=f"https://www.youtube.com/watch?v={vid}")) is None
        ]
        if not new_ids:
            continue

        channel_candidates = []
        # Fresh re-verify — the channel's ratio was true at approval time,
        # doesn't guarantee THIS video is still CC right now.
        for item in fetch_video_details(api_key, new_ids):
            if item.get("status", {}).get("license") != "creativeCommon":
                continue
            duration_raw = item.get("contentDetails", {}).get("duration")
            if not duration_raw:
                continue  # live/upcoming broadcasts and some edge cases omit this
            duration_s = _parse_iso8601_duration(duration_raw)
            if duration_s < min_duration:
                continue
            channel_candidates.append({
                "video_id": item["id"],
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "title": item["snippet"]["title"],
                "channel": ch["channel_name"],
                "channel_id": ch["channel_id"],
                "duration_s": duration_s,
            })
        if channel_candidates:
            per_channel.append(channel_candidates)

    interleaved = []
    for group in zip_longest(*per_channel, fillvalue=None):
        interleaved.extend(c for c in group if c is not None)
    return interleaved


def find_backlog_candidates(trust_db_path: str, dedup_dir: str, probe_glob: str, min_duration: float) -> list[dict]:
    """
    Sources candidates from previously-saved cc_supply_probe.py JSON output
    instead of live-polling channels' recent uploads.

    Exists because find_new_candidates() has a real blind spot: it only
    checks each channel's ~50 most recent uploads (chronological), but
    cc_supply_probe.py finds videos by *search* (any point in a channel's
    history, ranked by views) — for a prolific channel, its most-viewed CC
    video is very often NOT in its most-recent-50 window. That's the actual
    backlog ("these channels already have a lot of content posted") — this
    function is how to reach it. Re-checks against the CURRENT approved
    list, so a channel approved after a probe ran, or blocked since, is
    still respected rather than trusting the probe file's snapshot.
    """
    dedup = DeduplicationManager(dedup_dir)
    approved_ids = {
        c["channel_id"] for c in channel_trust.list_by_review_status(trust_db_path, channel_trust.REVIEW_APPROVED)
    }

    by_channel: dict[str, list[dict]] = {}
    for path in sorted(glob.glob(probe_glob)):
        try:
            with open(path, encoding="utf-8") as f:
                probe_results = json.load(f)
        except Exception as e:
            print(f"⚠️  Skipping unreadable probe file {path}: {e}")
            continue

        for keyword_result in probe_results:
            for v in keyword_result.get("qualifying", []):
                if v["channel_id"] not in approved_ids:
                    continue
                if v["duration_s"] < min_duration:
                    continue
                if dedup.check_video_duplicate(InputSource(source=v["url"])) is not None:
                    continue
                by_channel.setdefault(v["channel_id"], []).append({
                    "video_id": v["video_id"],
                    "url": v["url"],
                    "title": v["title"],
                    "channel": v["channel"],
                    "channel_id": v["channel_id"],
                    "duration_s": v["duration_s"],
                })

    interleaved = []
    per_channel_lists = list(by_channel.values())
    for group in zip_longest(*per_channel_lists, fillvalue=None):
        interleaved.extend(c for c in group if c is not None)
    # De-dup videos appearing under multiple search keywords, preserving order.
    seen_ids = set()
    unique = []
    for c in interleaved:
        if c["video_id"] not in seen_ids:
            seen_ids.add(c["video_id"])
            unique.append(c)
    return unique


def _acquire_lock(lock_path: str) -> bool:
    """
    Refuses to start a second run while one is still in progress — matters
    once this is scheduled frequently (e.g. hourly), since a slow run
    (a long source video) can easily still be going when the next trigger
    fires. Returns False (caller should exit) if another run holds the lock.
    """
    if os.path.exists(lock_path):
        try:
            with open(lock_path) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # raises OSError if that pid is gone
            print(f"⏭️  Another run (pid {pid}) is still in progress — skipping this trigger.")
            return False
        except (OSError, ValueError):
            pass  # stale lock (process gone, or unreadable) — safe to reclaim
    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-new", type=int, default=10, help="Safety cap: max new videos to process per run.")
    parser.add_argument("--per-channel-sample", type=int, default=50,
                         help="How many of each channel's most recent uploads to check (50 = YouTube API's max "
                         "per call, and covers full history for most small/medium channels).")
    parser.add_argument("--min-duration", type=float, default=180.0)
    parser.add_argument(
        "--from-probe-files", nargs="?", const="data/cc_supply_probe_*.json", default=None,
        help="Source candidates from saved cc_supply_probe.py JSON output instead of live-polling recent "
        "uploads — reaches each channel's full search-discovered backlog, not just its most-recent-50 "
        "window. Optional glob pattern (default: data/cc_supply_probe_*.json).",
    )
    parser.add_argument("--dry-run", action="store_true", help="List candidates without processing them.")
    parser.add_argument("--clips", type=int, default=1, help="Clips per video (passed to autopilot.py).")
    parser.add_argument("--enable-broll", action="store_true")
    parser.add_argument("--enable-bgm", action="store_true")
    parser.add_argument("--source-height", default="480")
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--whisper-device", default="cpu")
    parser.add_argument("--whisper-compute-type", default="int8")
    parser.add_argument("--face-detector", default="yolo", choices=["mediapipe", "yolo"])
    parser.add_argument("--upload-youtube", action="store_true", help="Pass through to autopilot.py.")
    parser.add_argument("--youtube-no-approval", action="store_true", help="Pass through to autopilot.py.")
    args = parser.parse_args()

    api_key = os.environ.get("YOUTUBE_DATA_API_KEY", "")
    if not api_key:
        print("❌ YOUTUBE_DATA_API_KEY not set — see .env.sample.")
        sys.exit(1)

    data_dir = os.path.join(os.getcwd(), "data")
    trust_db_path = os.path.join(data_dir, "channel_trust.db")

    lock_path = os.path.join(data_dir, "discover_new_clips.lock")
    if not args.dry_run and not _acquire_lock(lock_path):
        sys.exit(0)
    try:
        if args.from_probe_files:
            candidates = find_backlog_candidates(
                trust_db_path, data_dir, args.from_probe_files, args.min_duration
            )
        else:
            candidates = find_new_candidates(
                api_key, trust_db_path, data_dir, args.min_duration, args.per_channel_sample
            )
        candidates = candidates[: args.max_new]
        _process_candidates(candidates, args)
    finally:
        if os.path.exists(lock_path):
            os.remove(lock_path)


def _process_candidates(candidates: list[dict], args) -> None:
    print(f"\n📋 {len(candidates)} new candidate(s) (capped at --max-new {args.max_new}):")
    if not candidates:
        print("   (nothing new since the last run)")
        return
    for c in candidates:
        print(f"   • {c['channel']} — {c['title'][:70]} ({c['duration_s']/60:.1f}min)\n     {c['url']}")

    if args.dry_run:
        print("\n(dry run — nothing processed)")
        return

    for c in candidates:
        print(f"\n{'=' * 70}\n▶ Processing: {c['title']}\n{'=' * 70}")
        cmd = [
            sys.executable, "autopilot.py",
            "--url", c["url"],
            "--clips", str(args.clips),
            "--source-height", args.source_height,
            "--whisper-model", args.whisper_model,
            "--whisper-device", args.whisper_device,
            "--whisper-compute-type", args.whisper_compute_type,
            "--face-detector", args.face_detector,
            "--source-rights", "licensed_cc",
        ]
        if not args.enable_broll:
            cmd.append("--no-broll")
        if not args.enable_bgm:
            cmd.append("--no-bgm")
        if args.upload_youtube:
            cmd.append("--upload-youtube")
        if args.youtube_no_approval:
            cmd.append("--youtube-no-approval")

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"⚠️  autopilot.py exited {result.returncode} for {c['url']} — continuing to next candidate.")

    print("\n✅ Discovery run complete.")


if __name__ == "__main__":
    main()

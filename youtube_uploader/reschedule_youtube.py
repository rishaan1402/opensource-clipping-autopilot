#!/usr/bin/env python3
"""
reschedule_youtube.py — Reschedule YouTube videos that are still Scheduled/Private.

FUNCTION:
- Fetches the list of YouTube videos still Scheduled in the future.
- The video must still be `private` and have `status.publishAt`.
- Rewrites the publish schedule to a new interval, e.g. every 2 hours.
- Default mode is DRY-RUN, so it doesn't change YouTube directly.
- Use `--apply` to actually update the schedule on YouTube.

REQUIRED YOUTUBE API SCOPE:
This script uses `videos.update`, so the OAuth token must have at least one of the
following scopes:

    https://www.googleapis.com/auth/youtube
    https://www.googleapis.com/auth/youtube.force-ssl

Recommendation for this project:
Add `youtube.force-ssl` to `YOUTUBE_SCOPES` in `youtube_uploader.py`,
because the old scopes such as:

    https://www.googleapis.com/auth/youtube.upload
    https://www.googleapis.com/auth/youtube.readonly

are enough for upload/read, but not enough to update video metadata/schedule.

Example:

    YOUTUBE_SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ]

After changing the scope, the old token usually needs to be recreated:
    rm .credentials/youtube_token.json

Then run the OAuth login flow again so the new token has update permission.

IMPORTANT NOTES:
- `status.publishAt` can only be set if the video is still `private` and has never
  been published.
- `videos.update` has a quota cost of 50 units per video.
- An update with `part="status"` must send every status field you want to keep,
  because any mutable field that isn't sent may be treated as removed by the YouTube API.

Example:
    python reschedule_youtube.py

Apply to YouTube:
    python reschedule_youtube.py --apply

Start from a manual time:
    python reschedule_youtube.py --start-local "2026-08-22 08:00" --apply

2-hour interval:
    python reschedule_youtube.py --interval-hours 2 --apply
"""

import argparse
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from youtube_uploader import (
    get_youtube_service,
    parse_local_datetime,
    parse_rfc3339_to_local,
    to_rfc3339_utc,
    load_json_file,
    save_json_file,
    format_http_error,
)


MUTABLE_STATUS_KEYS = [
    "embeddable",
    "license",
    "privacyStatus",
    "publicStatsViewable",
    "selfDeclaredMadeForKids",
    "containsSyntheticMedia",
]


def get_uploads_playlist_id(youtube):
    resp = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()

    items = resp.get("items", [])
    if not items:
        raise RuntimeError("Channel for this account not found.")

    uploads_id = (
        items[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )

    if not uploads_id:
        raise RuntimeError("Uploads playlist not found.")

    return uploads_id


def chunked(items, size=50):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def list_scheduled_videos(youtube, tz_name="Asia/Makassar", max_pages=10):
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)

    uploads_playlist_id = get_uploads_playlist_id(youtube)

    scheduled = []
    page_token = None

    for _ in range(max_pages):
        playlist_resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        playlist_items = playlist_resp.get("items", [])
        video_ids = []

        for row in playlist_items:
            video_id = row.get("contentDetails", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)

        for id_batch in chunked(video_ids, 50):
            videos_resp = youtube.videos().list(
                part="id,status,snippet",
                id=",".join(id_batch),
            ).execute()

            for video in videos_resp.get("items", []):
                status = video.get("status", {})
                snippet = video.get("snippet", {})

                publish_at = status.get("publishAt")
                privacy_status = status.get("privacyStatus")

                if not publish_at:
                    continue

                publish_local = parse_rfc3339_to_local(publish_at, tz_name)
                if publish_local is None:
                    continue

                # Only take videos scheduled in the future.
                if publish_local <= now_local:
                    continue

                # A scheduled publishAt on YouTube must be private.
                if privacy_status != "private":
                    continue

                scheduled.append({
                    "video_id": video.get("id"),
                    "title": snippet.get("title", ""),
                    "old_publish_at_utc": publish_at,
                    "old_publish_at_local": publish_local,
                    "status": status,
                })

        page_token = playlist_resp.get("nextPageToken")
        if not page_token:
            break

    scheduled.sort(key=lambda x: x["old_publish_at_local"])
    return scheduled


def build_new_schedule(items, tz_name, interval_hours, start_local=None):
    if not items:
        return []

    if start_local:
        first_dt = parse_local_datetime(start_local, tz_name)
    else:
        # Default: keep the first video's schedule, tighten the rest.
        first_dt = items[0]["old_publish_at_local"]

    return [
        first_dt + timedelta(hours=i * interval_hours)
        for i in range(len(items))
    ]


def make_status_body(old_status, new_publish_local):
    new_status = {}

    # Preserve mutable status fields so the update doesn't wipe out other settings.
    for key in MUTABLE_STATUS_KEYS:
        if key in old_status:
            new_status[key] = old_status[key]

    new_status["privacyStatus"] = "private"
    new_status["publishAt"] = to_rfc3339_utc(new_publish_local)

    return new_status


def update_video_schedule(youtube, video, new_publish_local):
    body = {
        "id": video["video_id"],
        "status": make_status_body(video["status"], new_publish_local),
    }

    return youtube.videos().update(
        part="status",
        body=body,
    ).execute()


def update_manifest_file(manifest_file, updated_manifest_file, reschedule_rows, tz_name):
    if not manifest_file or not os.path.exists(manifest_file):
        return False

    manifest = load_json_file(manifest_file, default=[])
    if not isinstance(manifest, list):
        print(f"⚠️ Manifest is not a JSON list: {manifest_file}")
        return False

    schedule_by_id = {
        row["video_id"]: row
        for row in reschedule_rows
    }

    changed = 0
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    updated = deepcopy(manifest)

    for item in updated:
        video_id = item.get("youtube_video_id")
        if not video_id or video_id not in schedule_by_id:
            continue

        row = schedule_by_id[video_id]
        new_dt = row["new_publish_at_local"]

        item["youtube_scheduled_publish_local"] = new_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        item["youtube_scheduled_publish_utc"] = to_rfc3339_utc(new_dt)
        item["youtube_rescheduled_at_utc"] = now_utc
        changed += 1

    if changed:
        save_json_file(updated_manifest_file, updated)
        print(f"💾 Manifest updated too: {updated_manifest_file} ({changed} rows)")

    return bool(changed)


def print_plan(rows, tz_name):
    print("\nReschedule plan:")
    print("-" * 90)

    for i, row in enumerate(rows, start=1):
        old_txt = row["old_publish_at_local"].strftime("%Y-%m-%d %H:%M %Z")
        new_txt = row["new_publish_at_local"].strftime("%Y-%m-%d %H:%M %Z")

        print(f"{i:02d}. {row['title'][:55]}")
        print(f"    ID   : {row['video_id']}")
        print(f"    Old  : {old_txt}")
        print(f"    New  : {new_txt}")

    print("-" * 90)


def build_parser():
    p = argparse.ArgumentParser(
        description="Reschedule Scheduled/Private YouTube videos to a new interval.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument("--token-file", default=".credentials/youtube_token.json")
    p.add_argument("--tz-name", default="Asia/Makassar")
    p.add_argument("--interval-hours", type=int, default=2)
    p.add_argument("--start-local", default=None, help="Format: YYYY-MM-DD HH:MM")
    p.add_argument("--max-pages", type=int, default=10)
    p.add_argument("--apply", action="store_true", help="Actually update YouTube. Without this it's dry-run only.")

    p.add_argument("--manifest-file", default="outputs/render_manifest_uploaded.json")
    p.add_argument("--updated-manifest", default="outputs/render_manifest_rescheduled.json")

    return p


def main():
    args = build_parser().parse_args(sys.argv[1:])

    if not os.path.exists(args.token_file):
        print(f"❌ Token not found: {args.token_file}")
        sys.exit(1)

    if args.interval_hours <= 0:
        print("❌ --interval-hours must be greater than 0.")
        sys.exit(1)

    youtube = get_youtube_service(args.token_file)

    print("🔎 Fetching videos still Scheduled...")
    scheduled = list_scheduled_videos(
        youtube=youtube,
        tz_name=args.tz_name,
        max_pages=args.max_pages,
    )

    if not scheduled:
        print("ℹ️ No Scheduled/Private videos in the future.")
        return

    new_times = build_new_schedule(
        scheduled,
        tz_name=args.tz_name,
        interval_hours=args.interval_hours,
        start_local=args.start_local,
    )

    tz = ZoneInfo(args.tz_name)
    now_local = datetime.now(tz)

    rows = []
    for video, new_dt in zip(scheduled, new_times):
        rows.append({
            **video,
            "new_publish_at_local": new_dt,
            "new_publish_at_utc": to_rfc3339_utc(new_dt),
        })

    # Safety: don't set a schedule that's too close / already past.
    unsafe = [
        row for row in rows
        if row["new_publish_at_local"] <= now_local + timedelta(minutes=15)
    ]

    if unsafe:
        print("❌ Some new schedules are too close or already in the past.")
        print("   Use a --start-local further in the future.")
        print_plan(unsafe, args.tz_name)
        sys.exit(1)

    print_plan(rows, args.tz_name)

    if not args.apply:
        print("\n🧪 DRY-RUN only. No changes made on YouTube yet.")
        print("   Run again with --apply to actually reschedule.")
        return

    print("\n🚀 Starting schedule update on YouTube...")

    results = []

    for row in rows:
        try:
            update_video_schedule(youtube, row, row["new_publish_at_local"])

            print(f"✅ {row['video_id']} -> {row['new_publish_at_local'].strftime('%Y-%m-%d %H:%M %Z')}")

            results.append({
                "video_id": row["video_id"],
                "title": row["title"],
                "status": "rescheduled",
                "old_publish_at_local": row["old_publish_at_local"].strftime("%Y-%m-%d %H:%M:%S %Z"),
                "old_publish_at_utc": row["old_publish_at_utc"],
                "new_publish_at_local": row["new_publish_at_local"].strftime("%Y-%m-%d %H:%M:%S %Z"),
                "new_publish_at_utc": row["new_publish_at_utc"],
            })

        except Exception as e:
            err = format_http_error(e) if isinstance(e, HttpError) else str(e)

            print(f"❌ Failed to update {row['video_id']}: {err}")

            results.append({
                "video_id": row["video_id"],
                "title": row["title"],
                "status": "failed",
                "error": err,
            })

    os.makedirs("outputs", exist_ok=True)
    save_json_file("outputs/youtube_reschedule_results.json", results)
    print("💾 Reschedule log: outputs/youtube_reschedule_results.json")

    success_rows = [
        row for row in rows
        if any(
            r.get("video_id") == row["video_id"] and r.get("status") == "rescheduled"
            for r in results
        )
    ]

    update_manifest_file(
        manifest_file=args.manifest_file,
        updated_manifest_file=args.updated_manifest,
        reschedule_rows=success_rows,
        tz_name=args.tz_name,
    )

    print("\n✅ Done.")


if __name__ == "__main__":
    main()

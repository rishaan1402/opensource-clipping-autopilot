#!/usr/bin/env python3
"""
reschedule_youtube.py — Reschedule video YouTube yang masih Scheduled/Private.

FUNGSI:
- Mengambil daftar video YouTube yang masih Scheduled di masa depan.
- Video harus masih `private` dan punya `status.publishAt`.
- Mengubah ulang jadwal publish menjadi interval baru, misalnya tiap 2 jam.
- Default mode adalah DRY-RUN, jadi tidak langsung mengubah YouTube.
- Gunakan `--apply` untuk benar-benar update jadwal di YouTube.

SCOPE YOUTUBE API YANG DIBUTUHKAN:
Script ini memakai `videos.update`, jadi token OAuth harus punya minimal salah satu
scope berikut:

    https://www.googleapis.com/auth/youtube
    https://www.googleapis.com/auth/youtube.force-ssl

Rekomendasi untuk project ini:
Tambahkan `youtube.force-ssl` ke `YOUTUBE_SCOPES` di `youtube_uploader.py`,
karena scope lama seperti:

    https://www.googleapis.com/auth/youtube.upload
    https://www.googleapis.com/auth/youtube.readonly

cukup untuk upload/read, tetapi tidak cukup untuk update metadata/jadwal video.

Contoh:

    YOUTUBE_SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ]

Setelah scope diubah, token lama biasanya harus dibuat ulang:
    rm .credentials/youtube_token.json

Lalu jalankan flow login OAuth lagi agar token baru punya izin update.

CATATAN PENTING:
- `status.publishAt` hanya bisa diset kalau video masih `private` dan belum pernah
  dipublikasikan.
- `videos.update` memiliki biaya quota 50 unit per video.
- Update dengan `part="status"` harus mengirim field status yang ingin dipertahankan,
  karena field mutable yang tidak dikirim bisa dianggap dihapus oleh YouTube API.

Contoh:
    python reschedule_youtube.py

Apply ke YouTube:
    python reschedule_youtube.py --apply

Mulai dari waktu manual:
    python reschedule_youtube.py --start-local "2026-08-22 08:00" --apply

Interval 2 jam:
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
        raise RuntimeError("Channel milik akun ini tidak ditemukan.")

    uploads_id = (
        items[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )

    if not uploads_id:
        raise RuntimeError("Uploads playlist tidak ditemukan.")

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

                # Ambil hanya video scheduled di masa depan.
                if publish_local <= now_local:
                    continue

                # Scheduled publishAt YouTube harus private.
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
        # Default: jadwal video pertama tetap, video berikutnya dirapatkan.
        first_dt = items[0]["old_publish_at_local"]

    return [
        first_dt + timedelta(hours=i * interval_hours)
        for i in range(len(items))
    ]


def make_status_body(old_status, new_publish_local):
    new_status = {}

    # Preserve field status yang mutable agar update tidak menghapus setting lain.
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
        print(f"⚠️ Manifest bukan list JSON: {manifest_file}")
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
        print(f"💾 Manifest ikut diupdate: {updated_manifest_file} ({changed} row)")

    return bool(changed)


def print_plan(rows, tz_name):
    print("\nRencana reschedule:")
    print("-" * 90)

    for i, row in enumerate(rows, start=1):
        old_txt = row["old_publish_at_local"].strftime("%Y-%m-%d %H:%M %Z")
        new_txt = row["new_publish_at_local"].strftime("%Y-%m-%d %H:%M %Z")

        print(f"{i:02d}. {row['title'][:55]}")
        print(f"    ID   : {row['video_id']}")
        print(f"    Lama : {old_txt}")
        print(f"    Baru : {new_txt}")

    print("-" * 90)


def build_parser():
    p = argparse.ArgumentParser(
        description="Reschedule video YouTube Scheduled/Private menjadi interval baru.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument("--token-file", default=".credentials/youtube_token.json")
    p.add_argument("--tz-name", default="Asia/Makassar")
    p.add_argument("--interval-hours", type=int, default=2)
    p.add_argument("--start-local", default=None, help="Format: YYYY-MM-DD HH:MM")
    p.add_argument("--max-pages", type=int, default=10)
    p.add_argument("--apply", action="store_true", help="Benar-benar update YouTube. Tanpa ini hanya dry-run.")

    p.add_argument("--manifest-file", default="outputs/render_manifest_uploaded.json")
    p.add_argument("--updated-manifest", default="outputs/render_manifest_rescheduled.json")

    return p


def main():
    args = build_parser().parse_args(sys.argv[1:])

    if not os.path.exists(args.token_file):
        print(f"❌ Token tidak ditemukan: {args.token_file}")
        sys.exit(1)

    if args.interval_hours <= 0:
        print("❌ --interval-hours harus lebih dari 0.")
        sys.exit(1)

    youtube = get_youtube_service(args.token_file)

    print("🔎 Mengambil video yang masih Scheduled...")
    scheduled = list_scheduled_videos(
        youtube=youtube,
        tz_name=args.tz_name,
        max_pages=args.max_pages,
    )

    if not scheduled:
        print("ℹ️ Tidak ada video Scheduled/Private di masa depan.")
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

    # Safety: jangan set jadwal terlalu dekat / sudah lewat.
    unsafe = [
        row for row in rows
        if row["new_publish_at_local"] <= now_local + timedelta(minutes=15)
    ]

    if unsafe:
        print("❌ Ada jadwal baru yang terlalu dekat atau sudah lewat.")
        print("   Gunakan --start-local yang lebih jauh di masa depan.")
        print_plan(unsafe, args.tz_name)
        sys.exit(1)

    print_plan(rows, args.tz_name)

    if not args.apply:
        print("\n🧪 DRY-RUN saja. Belum ada perubahan di YouTube.")
        print("   Jalankan ulang dengan --apply untuk benar-benar reschedule.")
        return

    print("\n🚀 Mulai update jadwal di YouTube...")

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

            print(f"❌ Gagal update {row['video_id']}: {err}")

            results.append({
                "video_id": row["video_id"],
                "title": row["title"],
                "status": "failed",
                "error": err,
            })

    os.makedirs("outputs", exist_ok=True)
    save_json_file("outputs/youtube_reschedule_results.json", results)
    print("💾 Log reschedule: outputs/youtube_reschedule_results.json")

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

    print("\n✅ Selesai.")


if __name__ == "__main__":
    main()
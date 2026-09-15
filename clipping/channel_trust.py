"""
clipping.channel_trust — Channel-level Creative Commons trust check.

A single CC-tagged video isn't enough signal on its own. The recurring
failure mode found in cc_supply_probe.py's first real run: a channel with
exactly one CC-tagged video is often a compilation/reaction/news-repost
where the uploader tagged CC over footage they didn't fully own (a war-zone
drone clip re-hosted by a news aggregator, for example) — the tag doesn't
retroactively clear rights the uploader never had. A channel that releases
CC content *systematically* (a course channel, a stock-footage library) is
a categorically different, much safer signal.

This samples a channel's recent uploads and computes what fraction are
genuinely CC-licensed (re-verified via videos.list, not trusted from
search-time flags). Results are cached in SQLite — the same channel gets
asked about repeatedly across probe runs and live processing, and each
check costs real API quota.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

MIN_SAMPLE = 5       # below this many resolvable uploads, we don't have enough signal
MIN_CC_COUNT = 2      # a single CC video, even in a small sample, isn't "systematic"
MIN_CC_RATIO = 0.30   # channels legitimately mix CC and standard uploads — don't require majority

VERDICT_TRUSTED = "trusted"
VERDICT_ISOLATED = "isolated"
VERDICT_INSUFFICIENT_DATA = "insufficient_data"
VERDICT_CHECK_FAILED = "check_failed"

# A ratio check answers "does this channel do this a lot", not "should this
# channel be trusted to do it" — a news-repost aggregator can systematically
# CC-tag footage it never fully owned (see the 'Kanal13' war-footage case
# found in the first live probe run: verdict=trusted, still not something to
# auto-publish from). review_status is the human decision that ratio alone
# can't make, checked once per channel rather than once per clip.
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_BLOCKED = "blocked"

# Names/titles matching these read as the Kanal13 pattern found in the first
# live probe run: a generic "give away footage" or news-repost brand, the
# recurring case where a CC tag doesn't guarantee the uploader owned what's
# in the video. Any hit here means "never auto-approve, always route to
# manual review" regardless of how consistent the channel's CC ratio is.
RED_FLAG_KEYWORDS = [
    "no copyright", "copyright free", "royalty free", "free footage",
    "free video", "free hd video", "free stock", "stock footage",
    "ultra hd video", "4k video", "hd video", "no copyright sounds",
    "breaking news", "breaking:", "watch:", "news18", "news 18",
    "24/7 news", "world news",
]

# Auto-approve threshold — deliberately stricter than the plain "trusted"
# verdict (MIN_CC_COUNT=2, MIN_CC_RATIO=0.30): a channel needs a large,
# heavily-CC sample AND no red-flag hit to skip human review entirely.
AUTO_APPROVE_MIN_CC_COUNT = 10
AUTO_APPROVE_MIN_CC_RATIO = 0.70


def _find_red_flags(channel_name: str, titles: list[str]) -> list[str]:
    haystack = " | ".join([channel_name or ""] + titles).lower()
    return [kw for kw in RED_FLAG_KEYWORDS if kw in haystack]


def default_db_path(outputs_dir: str) -> str:
    """Same sibling-'data'-directory convention as clipping.creators_db."""
    data_dir = os.path.join(os.path.dirname(outputs_dir.rstrip(os.sep)), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "channel_trust.db")


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_trust (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT,
                sample_size INTEGER,
                cc_count INTEGER,
                cc_ratio REAL,
                verdict TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending',
                reviewed_at TEXT,
                red_flags TEXT NOT NULL DEFAULT '',
                auto_approved INTEGER NOT NULL DEFAULT 0,
                checked_at TEXT NOT NULL
            )
            """
        )
        # Migrations for DBs created before these columns existed.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(channel_trust)")}
        if "review_status" not in existing_cols:
            conn.execute(
                f"ALTER TABLE channel_trust ADD COLUMN review_status TEXT NOT NULL DEFAULT '{REVIEW_PENDING}'"
            )
        if "reviewed_at" not in existing_cols:
            conn.execute("ALTER TABLE channel_trust ADD COLUMN reviewed_at TEXT")
        if "red_flags" not in existing_cols:
            conn.execute("ALTER TABLE channel_trust ADD COLUMN red_flags TEXT NOT NULL DEFAULT ''")
        if "auto_approved" not in existing_cols:
            conn.execute("ALTER TABLE channel_trust ADD COLUMN auto_approved INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _get_uploads_playlist_id(api_key: str, channel_id: str) -> Optional[str]:
    resp = requests.get(
        CHANNELS_URL,
        params={"part": "contentDetails", "id": channel_id, "key": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _get_recent_video_ids(api_key: str, uploads_playlist_id: str, sample_size: int) -> list[str]:
    resp = requests.get(
        PLAYLIST_ITEMS_URL,
        params={
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": min(sample_size, 50),
            "key": api_key,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return [item["contentDetails"]["videoId"] for item in resp.json().get("items", [])]


def check_channel_consistency(api_key: str, channel_id: str, channel_name: str = "", sample_size: int = 20) -> dict:
    """
    Fresh (uncached) check: what fraction of this channel's recent uploads
    are genuinely CC-licensed? Never trusts the search-time flag — every
    sampled video's license is re-verified via videos.list. Also scans the
    channel name and sampled video titles for RED_FLAG_KEYWORDS, so a caller
    can decide whether this channel is even eligible for auto-approval.
    """
    try:
        uploads_playlist_id = _get_uploads_playlist_id(api_key, channel_id)
        if not uploads_playlist_id:
            return {"sample_size": 0, "cc_count": 0, "cc_ratio": 0.0, "verdict": VERDICT_CHECK_FAILED, "red_flags": []}

        video_ids = _get_recent_video_ids(api_key, uploads_playlist_id, sample_size)
        if len(video_ids) < MIN_SAMPLE:
            return {
                "sample_size": len(video_ids), "cc_count": 0, "cc_ratio": 0.0,
                "verdict": VERDICT_INSUFFICIENT_DATA, "red_flags": [],
            }

        cc_count = 0
        titles = []
        for batch in _chunked(video_ids, 50):
            resp = requests.get(
                VIDEOS_URL,
                params={"part": "status,snippet", "id": ",".join(batch), "key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                if item.get("status", {}).get("license") == "creativeCommon":
                    cc_count += 1
                title = item.get("snippet", {}).get("title")
                if title:
                    titles.append(title)

        cc_ratio = cc_count / len(video_ids)
        verdict = (
            VERDICT_TRUSTED
            if cc_count >= MIN_CC_COUNT and cc_ratio >= MIN_CC_RATIO
            else VERDICT_ISOLATED
        )
        red_flags = _find_red_flags(channel_name, titles)
        return {
            "sample_size": len(video_ids), "cc_count": cc_count, "cc_ratio": cc_ratio,
            "verdict": verdict, "red_flags": red_flags,
        }

    except Exception as exc:  # noqa: BLE001 — surfaced in the returned dict, not swallowed silently
        print(f"⚠️  Channel trust check failed for {channel_id}: {exc}")
        return {"sample_size": 0, "cc_count": 0, "cc_ratio": 0.0, "verdict": VERDICT_CHECK_FAILED, "red_flags": []}


def get_or_check_channel_trust(
    api_key: str,
    db_path: str,
    channel_id: str,
    channel_name: Optional[str] = None,
    sample_size: int = 20,
    max_age_days: int = 30,
) -> dict:
    """Cached wrapper — re-checks only if no cached verdict or it's stale."""
    init_db(db_path)
    now = datetime.now(timezone.utc)

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM channel_trust WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        if row:
            checked_at = datetime.fromisoformat(row["checked_at"])
            if now - checked_at < timedelta(days=max_age_days):
                return dict(row)

    result = check_channel_consistency(api_key, channel_id, channel_name or "", sample_size)
    red_flags = result.pop("red_flags", [])

    # Auto-approve only a deliberately narrow band: a large, heavily-CC
    # sample AND zero red-flag hits. Everything else — including any
    # channel with a red flag, no matter how high its ratio — lands in
    # REVIEW_PENDING for a human to actually look at. This is what makes
    # "accept somewhat more risk" bounded rather than open-ended: it cuts
    # review volume on the unambiguous majority without silently trusting
    # the exact Kanal13-shaped case this table exists to catch.
    auto_approved = (
        result["verdict"] == VERDICT_TRUSTED
        and result["cc_count"] >= AUTO_APPROVE_MIN_CC_COUNT
        and result["cc_ratio"] >= AUTO_APPROVE_MIN_CC_RATIO
        and not red_flags
    )

    result["channel_id"] = channel_id
    result["channel_name"] = channel_name
    result["checked_at"] = now.isoformat()
    result["red_flags"] = ", ".join(red_flags)
    result["auto_approved"] = 1 if auto_approved else 0
    result["review_status"] = REVIEW_APPROVED if auto_approved else REVIEW_PENDING  # only used on first INSERT

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO channel_trust
                (channel_id, channel_name, sample_size, cc_count, cc_ratio, verdict,
                 review_status, red_flags, auto_approved, checked_at)
            VALUES (:channel_id, :channel_name, :sample_size, :cc_count, :cc_ratio, :verdict,
                    :review_status, :red_flags, :auto_approved, :checked_at)
            ON CONFLICT(channel_id) DO UPDATE SET
                channel_name=excluded.channel_name, sample_size=excluded.sample_size,
                cc_count=excluded.cc_count, cc_ratio=excluded.cc_ratio,
                verdict=excluded.verdict, red_flags=excluded.red_flags, checked_at=excluded.checked_at
                -- review_status/reviewed_at/auto_approved deliberately NOT overwritten here —
                -- a routine trust re-check must never silently reset a human's approve/block
                -- decision, or relabel a manually-approved channel as auto-approved.
            """,
            result,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM channel_trust WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return dict(row)


def set_review_status(db_path: str, channel_id: str, review_status: str) -> None:
    if review_status not in (REVIEW_PENDING, REVIEW_APPROVED, REVIEW_BLOCKED):
        raise ValueError(f"Invalid review_status: {review_status!r}")
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE channel_trust SET review_status = ?, reviewed_at = ? WHERE channel_id = ?",
            (review_status, datetime.now(timezone.utc).isoformat(), channel_id),
        )
        conn.commit()


def list_by_review_status(db_path: str, review_status: str) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM channel_trust WHERE review_status = ? ORDER BY cc_count DESC",
            (review_status,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_auto_approved(db_path: str) -> list[dict]:
    """Channels that skipped human review entirely via the auto-approve heuristic —
    the audit trail for 'accept somewhat more risk' (see AUTO_APPROVE_MIN_CC_COUNT/RATIO)."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM channel_trust WHERE auto_approved = 1 ORDER BY checked_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ==============================================================================
# CLI — python -m clipping.channel_trust <command> ...
# ==============================================================================

def _cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Channel-level CC trust review")
    p.add_argument("--db", default=os.path.join("data", "channel_trust.db"))
    sub = p.add_subparsers(dest="command", required=True)

    p_pending = sub.add_parser(
        "pending",
        help="List trusted-verdict channels awaiting a one-time human decision "
        "('isolated'-verdict channels are already blocked by the ratio check and never need review)",
    )
    p_pending.add_argument("--all", action="store_true", help="Include isolated-verdict channels too")
    p_approve = sub.add_parser("approve", help="Approve a channel — its CC content can now auto-publish")
    p_approve.add_argument("channel_id")
    p_block = sub.add_parser("block", help="Block a channel — its CC content will never auto-publish")
    p_block.add_argument("channel_id")
    sub.add_parser("auto-approved", help="Audit trail: channels that skipped human review via the auto-approve heuristic")

    args = p.parse_args()

    if args.command == "pending":
        rows = list_by_review_status(args.db, REVIEW_PENDING)
        if not args.all:
            rows = [r for r in rows if r["verdict"] == VERDICT_TRUSTED]
        if not rows:
            print("(nothing pending)")
        for r in rows:
            print(
                f"{r['channel_id']:<28} {r['channel_name']:<30} "
                f"{r['cc_count']}/{r['sample_size']} CC ({r['cc_ratio']:.0%})  verdict={r['verdict']}"
            )
    elif args.command == "approve":
        set_review_status(args.db, args.channel_id, REVIEW_APPROVED)
        print(f"✅ {args.channel_id} approved")
    elif args.command == "block":
        set_review_status(args.db, args.channel_id, REVIEW_BLOCKED)
        print(f"🚫 {args.channel_id} blocked")
    elif args.command == "auto-approved":
        rows = list_auto_approved(args.db)
        if not rows:
            print("(none yet)")
        for r in rows:
            print(
                f"{r['channel_id']:<28} {r['channel_name']:<30} "
                f"{r['cc_count']}/{r['sample_size']} CC ({r['cc_ratio']:.0%})  checked={r['checked_at'][:10]}"
            )
        print(f"\n{len(rows)} channel(s) auto-approved without human review. "
              f"Use 'block <channel_id>' on any of these to revoke.")


if __name__ == "__main__":
    _cli()

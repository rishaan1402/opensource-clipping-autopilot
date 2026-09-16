#!/usr/bin/env python3
"""
cc_supply_probe.py — Validate Creative Commons supply before building Feed A.

Answers one question with real numbers instead of assumptions: for a given
niche, how much genuinely usable (long enough, watched enough) Creative
Commons–licensed YouTube content actually exists? If the answer is "not
much," the CC-discovery feed isn't worth automating for that niche — better
to find that out with one API call than after building a poller for it.

Usage:
    python cc_supply_probe.py --keywords "productivity tips" "study with me"
    python cc_supply_probe.py --keywords "history explained" --min-duration 240

Requires YOUTUBE_DATA_API_KEY in .env (Google Cloud Console -> enable
"YouTube Data API v3" -> Credentials -> API key. No OAuth needed — this only
reads public search/video data).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from clipping import channel_trust

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# search.list quota cost is 100 units/call against the default 10,000/day
# project quota — keep this conservative so the probe itself never eats a
# meaningful slice of a day's budget.
_ISO8601_DURATION_RE = re.compile(
    r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def _parse_iso8601_duration(duration: str) -> float:
    """PT1H2M3S -> 3723.0 seconds. Returns 0.0 on an unparseable string."""
    match = _ISO8601_DURATION_RE.fullmatch(duration or "")
    if not match:
        return 0.0
    parts = match.groupdict()
    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)
    return float(hours * 3600 + minutes * 60 + seconds)


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def search_cc_candidates(
    api_key: str,
    keyword: str,
    video_duration: str,
    max_results: int,
    published_after: str | None = None,
) -> list[dict]:
    """One search.list call, filtered to videoLicense=creativeCommon.

    published_after (RFC 3339, e.g. '2026-03-01T00:00:00Z') biases results
    toward content that's breaking out *now* rather than old evergreen
    videos that just accumulated views over years — closer to what "viral"
    actually means for this task than raw lifetime view count alone.
    """
    params = {
        "part": "id,snippet",
        "q": keyword,
        "type": "video",
        "videoLicense": "creativeCommon",
        "videoDuration": video_duration,
        "order": "viewCount",
        "maxResults": min(max_results, 50),
        "key": api_key,
    }
    if published_after:
        params["publishedAfter"] = published_after

    resp = requests.get(SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("items", [])


def fetch_video_details(api_key: str, video_ids: list[str]) -> list[dict]:
    """Batched videos.list call (up to 50 ids) — re-verifies license + gets duration/views."""
    out = []
    for batch in _chunked(video_ids, 50):
        resp = requests.get(
            VIDEOS_URL,
            params={
                "part": "status,contentDetails,statistics,snippet",
                "id": ",".join(batch),
                "key": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        out.extend(resp.json().get("items", []))
    return out


def probe_keyword(
    api_key: str,
    keyword: str,
    min_duration: float,
    max_results: int,
    trust_db_path: str,
    min_views: int = 0,
    min_view_velocity: float = 0.0,
    published_after_days: float | None = None,
) -> dict:
    print(f"\n🔎 '{keyword}'")

    published_after = None
    if published_after_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=published_after_days)
        published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    candidates = []
    for duration_bucket in ("medium", "long"):  # medium=4-20min, long=20min+
        try:
            candidates.extend(
                search_cc_candidates(api_key, keyword, duration_bucket, max_results, published_after)
            )
        except requests.HTTPError as exc:
            print(f"   ⚠️  search.list failed for duration={duration_bucket}: {exc}")

    video_ids = [c["id"]["videoId"] for c in candidates if c.get("id", {}).get("videoId")]
    video_ids = list(dict.fromkeys(video_ids))  # dedupe, preserve order
    if not video_ids:
        print("   → 0 candidates returned by search.list")
        return {"keyword": keyword, "qualifying": [], "total_found": 0}

    details = fetch_video_details(api_key, video_ids)

    now = datetime.now(timezone.utc)
    qualifying = []
    for item in details:
        license_status = item.get("status", {}).get("license")
        if license_status != "creativeCommon":
            continue  # search-time flag can lag reality — re-verified here
        duration_s = _parse_iso8601_duration(item["contentDetails"]["duration"])
        if duration_s < min_duration:
            continue

        view_count = int(item.get("statistics", {}).get("viewCount", 0))
        if view_count < min_views:
            continue

        published_at = item["snippet"].get("publishedAt", "")
        try:
            published_dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_days = max((now - published_dt).total_seconds() / 86400.0, 1.0)
        except ValueError:
            age_days = None
        # Views/day since publish — a video with 200k views in 2 weeks is
        # "viral" in a way a video with 200k views over 3 years is not, and
        # raw lifetime view_count can't tell those apart.
        view_velocity = (view_count / age_days) if age_days else 0.0
        if view_velocity < min_view_velocity:
            continue

        qualifying.append({
            "video_id": item["id"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "channel_id": item["snippet"]["channelId"],
            "duration_s": duration_s,
            "view_count": view_count,
            "published_at": published_at,
            "age_days": round(age_days, 1) if age_days else None,
            "view_velocity": round(view_velocity, 1),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        })

    # Rank by view velocity, not raw lifetime views — the point of the
    # "harsher" filtering is to surface content that's actually breaking out,
    # not just old videos that slowly accumulated a large total.
    qualifying.sort(key=lambda v: v["view_velocity"], reverse=True)
    unique_channels = len({v["channel_id"] for v in qualifying})
    views = [v["view_count"] for v in qualifying]

    print(f"   → {len(video_ids)} CC candidates found, {len(qualifying)} qualify "
          f"(license re-verified + duration ≥ {min_duration:.0f}s"
          + (f", views ≥ {min_views:,}" if min_views else "")
          + (f", velocity ≥ {min_view_velocity:,.0f}/day" if min_view_velocity else "")
          + ")")
    print(f"   → {unique_channels} distinct channels")
    if views:
        print(f"   → view count: min={min(views):,}  median={int(statistics.median(views)):,}  max={max(views):,}")

    # Channel-consistency pass: a single CC-tagged video isn't enough signal —
    # check whether each unique channel releases CC content systematically,
    # once per channel (cached), not once per video.
    channels_seen = {}
    for v in qualifying:
        if v["channel_id"] not in channels_seen:
            channels_seen[v["channel_id"]] = channel_trust.get_or_check_channel_trust(
                api_key, trust_db_path, v["channel_id"], v["channel"]
            )
        v["channel_trust"] = channels_seen[v["channel_id"]]["verdict"]

    trusted = [v for v in qualifying if v["channel_trust"] == channel_trust.VERDICT_TRUSTED]
    verdict_counts = {}
    for verdict in channels_seen.values():
        verdict_counts[verdict["verdict"]] = verdict_counts.get(verdict["verdict"], 0) + 1

    print(f"   → channel trust: {len(trusted)}/{len(qualifying)} videos from "
          f"{verdict_counts.get(channel_trust.VERDICT_TRUSTED, 0)}/{len(channels_seen)} trusted channels "
          f"({dict(verdict_counts)})")
    if trusted:
        print("   → top 3 by view velocity (trusted channels only):")
        for v in trusted[:3]:
            mins = v["duration_s"] / 60
            print(
                f"      • {v['view_velocity']:>8,.0f}/day ({v['view_count']:>10,} views, "
                f"{v['age_days']:.0f}d old) | {mins:5.1f}min | {v['channel']} — {v['title'][:50]}"
            )

    return {
        "keyword": keyword,
        "total_found": len(video_ids),
        "qualifying": qualifying,
        "trusted": trusted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keywords", nargs="+", required=True, help="One or more niche keywords/queries to probe")
    parser.add_argument("--min-duration", type=float, default=180.0,
                         help="Minimum source video length in seconds (default: 180 — needs headroom for a 20-179s highlight)")
    parser.add_argument("--max-results", type=int, default=50, help="Max search results per keyword per duration bucket (max 50)")
    parser.add_argument("--min-views", type=int, default=0,
                         help="Drop candidates below this lifetime view count (default: 0, no floor).")
    parser.add_argument("--min-view-velocity", type=float, default=0.0,
                         help="Drop candidates below this views/day-since-published rate (default: 0, no floor). "
                         "A stronger 'is this actually breaking out' signal than raw view count, since it can't "
                         "be inflated by an old video that just slowly accumulated views over years.")
    parser.add_argument("--published-after-days", type=float, default=None,
                         help="Only search videos published within this many days (default: none — all time). "
                         "Set this to bias toward currently-viral content instead of old evergreen uploads.")
    parser.add_argument("--out", default=None, help="Path to save full JSON results (default: data/cc_supply_probe_<timestamp>.json)")
    args = parser.parse_args()

    api_key = os.environ.get("YOUTUBE_DATA_API_KEY", "")
    if not api_key:
        print("❌ YOUTUBE_DATA_API_KEY not set. Get one at:")
        print("   https://console.cloud.google.com/apis/credentials")
        print("   (enable 'YouTube Data API v3' first, then create an API key — no OAuth needed)")
        print("   Add it to .env as YOUTUBE_DATA_API_KEY=...")
        sys.exit(1)

    print("=" * 70)
    print("🎬 Creative Commons Supply Probe")
    print("=" * 70)
    print(f"   Keywords     : {', '.join(args.keywords)}")
    print(f"   Min duration : {args.min_duration:.0f}s")
    if args.min_views:
        print(f"   Min views    : {args.min_views:,}")
    if args.min_view_velocity:
        print(f"   Min velocity : {args.min_view_velocity:,.0f} views/day")
    if args.published_after_days:
        print(f"   Published within: last {args.published_after_days:.0f} days")
    print("=" * 70)

    data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    trust_db_path = os.path.join(data_dir, "channel_trust.db")

    results = [
        probe_keyword(
            api_key, kw, args.min_duration, args.max_results, trust_db_path,
            min_views=args.min_views,
            min_view_velocity=args.min_view_velocity,
            published_after_days=args.published_after_days,
        )
        for kw in args.keywords
    ]

    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    total_qualifying = 0
    total_trusted = 0
    for r in results:
        n, t = len(r["qualifying"]), len(r["trusted"])
        total_qualifying += n
        total_trusted += t
        verdict = "✅ viable" if t >= 15 else ("⚠️  thin" if t >= 5 else "❌ not enough trusted supply")
        print(f"   {r['keyword']:<30} {n:>4} qualifying -> {t:>4} trusted   {verdict}")
    print(f"\n   Total qualifying: {total_qualifying}   Total from trusted channels: {total_trusted}")
    print("   ('qualifying' = license + duration only. 'trusted' = channel systematically")
    print("    releases CC content, not just this one video — see clipping/channel_trust.py.")
    print("    Rule of thumb: <5 trusted videos in a niche means it isn't worth automating yet.)")

    pending = channel_trust.list_by_review_status(trust_db_path, channel_trust.REVIEW_PENDING)
    trusted_pending = [c for c in pending if c["verdict"] == channel_trust.VERDICT_TRUSTED]
    if trusted_pending:
        print(f"\n   ⏳ {len(trusted_pending)} trusted channels await a one-time human decision "
              "before any of their content can auto-publish:")
        for c in sorted(trusted_pending, key=lambda c: c["cc_count"], reverse=True)[:10]:
            print(f"      {c['channel_id']:<28} {c['channel_name']:<30} {c['cc_count']}/{c['sample_size']} CC")
        if len(trusted_pending) > 10:
            print(f"      ... and {len(trusted_pending) - 10} more")
        print("   Review with: python -m clipping.channel_trust pending")
        print("   Then:        python -m clipping.channel_trust approve <channel_id>")

    out_path = args.out
    if not out_path:
        data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = os.path.join(data_dir, f"cc_supply_probe_{stamp}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Full results saved to {out_path}")


if __name__ == "__main__":
    main()

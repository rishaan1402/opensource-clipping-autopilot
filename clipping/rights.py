"""
clipping.rights — Source-rights gate.

Every clip source must declare where its legal right to be clipped and
re-published comes from, before any download/AI/render cost is spent.
This module is the single place that:

  1. Defines the taxonomy (SOURCE_RIGHTS_CHOICES).
  2. Validates static config combinations at CLI-parse time
     (validate_source_rights_args).
  3. Re-checks the runtime claim right after download, before spending
     Whisper/Gemini cost on it (enforce_source_rights_or_raise).
  4. Builds the attribution string owed to the original creator, where
     one is owed (build_attribution_source_url).

Deliberately does NOT try to auto-detect rights from raw content —
that always requires either a machine-checkable fact (a license flag)
or a human decision recorded ahead of time (a creator agreement). Both
are handled explicitly; nothing here silently decides "this is
probably fine."
"""

from __future__ import annotations

import os
from typing import Optional, TypedDict

import requests

from . import creators_db, channel_trust

# ==============================================================================
# TAXONOMY
# ==============================================================================

RIGHTS_OWNED = "owned"
RIGHTS_LICENSED_CC = "licensed_cc"
RIGHTS_PERMISSIONED = "permissioned"
RIGHTS_TRANSFORMED_COMMENTARY = "transformed_commentary"
RIGHTS_UNKNOWN = "unknown"

SOURCE_RIGHTS_CHOICES = [
    RIGHTS_OWNED,
    RIGHTS_LICENSED_CC,
    RIGHTS_PERMISSIONED,
    RIGHTS_TRANSFORMED_COMMENTARY,
    RIGHTS_UNKNOWN,
]

# Rights buckets that are allowed to feed an unattended/autonomous run
# (a future scheduler should check this before enqueueing a source).
# "unknown" and "transformed_commentary" are deliberately excluded from
# the second list's automation-by-default assumption at the call site —
# transformed_commentary is allowed here because its risk is mitigated
# by a *mandatory* pipeline behavior (forced --voiceover), not by human
# review, but callers building a scheduler should still weight it as
# higher-risk than owned/licensed_cc/permissioned.
AUTOMATABLE_RIGHTS = {
    RIGHTS_OWNED,
    RIGHTS_LICENSED_CC,
    RIGHTS_PERMISSIONED,
    RIGHTS_TRANSFORMED_COMMENTARY,
}


class SourceInfo(TypedDict, total=False):
    video_id: Optional[str]
    title: Optional[str]
    uploader: Optional[str]
    channel_id: Optional[str]
    channel_url: Optional[str]
    webpage_url: Optional[str]
    license: Optional[str]  # yt-dlp: "Creative Commons Attribution" or "Standard YouTube License"
    platform: str


# ==============================================================================
# STATIC VALIDATION (CLI-parse time — no network, no DB writes)
# ==============================================================================

def validate_source_rights_args(args, parser, creators_db_path: str) -> None:
    """
    Validate --source-rights combinations against the rest of argparse's
    Namespace. Call parser.error(...) (never returns) on any violation,
    mirroring the existing validation style in clipping.config.build_config.
    """
    rights = getattr(args, "source_rights", RIGHTS_UNKNOWN)

    if rights == RIGHTS_TRANSFORMED_COMMENTARY and not getattr(args, "voiceover", False):
        parser.error(
            "--source-rights transformed_commentary requires --voiceover. "
            "The fair-use position this bucket relies on is 'substantial original "
            "commentary replacing the source', which only exists once voice-over is on."
        )

    if rights == RIGHTS_PERMISSIONED:
        creator_id = getattr(args, "creator_permission_id", None)
        if not creator_id:
            parser.error(
                "--source-rights permissioned requires --creator-permission-id "
                "(the numeric id of an 'agreed' row in the creators registry — "
                "see clipping/creators_db.py)."
            )
        record = creators_db.get_creator_by_id(creators_db_path, creator_id)
        if record is None:
            parser.error(
                f"--creator-permission-id {creator_id} does not exist in "
                f"the creators registry ({creators_db_path})."
            )
        elif record["outreach_status"] != "agreed":
            parser.error(
                f"--creator-permission-id {creator_id} refers to "
                f"'{record['channel_name']}', whose outreach_status is "
                f"'{record['outreach_status']}', not 'agreed'. Cannot auto-publish "
                "against an unconfirmed or revoked permission."
            )


# ==============================================================================
# RUNTIME ENFORCEMENT (after download — network + DB reads allowed)
# ==============================================================================

def fetch_youtube_license_status(video_id: str, api_key: str) -> Optional[str]:
    """
    Query the YouTube Data API v3 for a video's declared license.

    Returns "creativeCommon", "youtube" (standard license), or None if the
    lookup failed (network error, bad key, video not found — treated as
    "could not verify", never as "is CC").
    """
    if not video_id or not api_key:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "status", "id": video_id, "key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None
        return items[0].get("status", {}).get("license")
    except Exception as exc:  # noqa: BLE001 — surfaced by caller, not swallowed
        print(f"⚠️  Gagal verifikasi lisensi YouTube untuk {video_id}: {exc}")
        return None


def enforce_source_rights_or_raise(cfg, source_info: SourceInfo) -> None:
    """
    Runtime re-check, called right after download and before Whisper/Gemini
    spend any money on the source. Raises RuntimeError (aborts the run) on
    any violation — this function never silently degrades to "unknown".
    """
    rights = getattr(cfg, "source_rights", RIGHTS_UNKNOWN)

    if rights == RIGHTS_LICENSED_CC:
        platform = source_info.get("platform", "youtube")
        if platform != "youtube":
            raise RuntimeError(
                "--source-rights licensed_cc is currently only verifiable for "
                f"YouTube sources (got platform={platform}). Re-verification via "
                "the YouTube Data API is the only automated check this module "
                "implements — use 'permissioned' or 'owned' for other platforms."
            )
        video_id = source_info.get("video_id")
        api_key = getattr(cfg, "youtube_data_api_key", "")
        if not api_key:
            raise RuntimeError(
                "--source-rights licensed_cc requires YOUTUBE_DATA_API_KEY to be "
                "set, so the license can be re-verified at process time (a license "
                "can change after upload — the discovery-time check is not enough)."
            )
        license_status = fetch_youtube_license_status(video_id, api_key)
        if license_status != "creativeCommon":
            raise RuntimeError(
                f"--source-rights licensed_cc was declared for video {video_id}, "
                f"but its current license is '{license_status}', not "
                "'creativeCommon'. Refusing to process — the license may have "
                "been changed after this source was queued."
            )
        print(f"   ✅ Lisensi Creative Commons terverifikasi untuk video {video_id}.")

        # A single CC-tagged video isn't enough signal on its own — see
        # clipping/channel_trust.py's docstring for why (compilation/repost
        # videos that shouldn't have been tagged CC in the first place).
        channel_id = source_info.get("channel_id")
        if channel_id:
            db_path = getattr(
                cfg, "channel_trust_db_path", channel_trust.default_db_path(cfg.outputs_dir)
            )
            trust = channel_trust.get_or_check_channel_trust(
                api_key, db_path, channel_id, source_info.get("uploader")
            )
            if trust["verdict"] != channel_trust.VERDICT_TRUSTED:
                raise RuntimeError(
                    f"--source-rights licensed_cc: video {video_id}'s channel "
                    f"({source_info.get('uploader')}) does not systematically "
                    f"release CC content (verdict: {trust['verdict']}, "
                    f"{trust.get('cc_count', 0)}/{trust.get('sample_size', 0)} recent "
                    "uploads are CC). Refusing to auto-trust an isolated CC tag."
                )
            if trust["review_status"] != channel_trust.REVIEW_APPROVED:
                raise RuntimeError(
                    f"--source-rights licensed_cc: channel {source_info.get('uploader')} "
                    f"({channel_id}) systematically CC-tags content but has not been "
                    f"through the one-time human review gate (status: {trust['review_status']}). "
                    "A ratio check alone can't tell a course/stock-footage channel apart from "
                    "a news-repost aggregator that over-licenses footage it doesn't fully own — "
                    f"run: python -m clipping.channel_trust approve {channel_id}"
                )
            print(
                f"   ✅ Channel trust verified & approved: {trust['cc_count']}/{trust['sample_size']} "
                f"recent uploads are CC-licensed."
            )

    elif rights == RIGHTS_PERMISSIONED:
        creator_id = getattr(cfg, "creator_permission_id", None)
        db_path = getattr(cfg, "creators_db_path", creators_db.default_db_path(cfg.outputs_dir))
        record = creators_db.get_creator_by_id(db_path, creator_id)
        if record is None or record["outreach_status"] != "agreed":
            status = record["outreach_status"] if record else "not found"
            raise RuntimeError(
                f"--creator-permission-id {creator_id} is no longer valid at "
                f"process time (status: {status}). A permission can be revoked "
                "between queueing and processing — re-checked here, not just at "
                "CLI-parse time."
            )
        print(
            f"   ✅ Izin kreator terverifikasi: '{record['channel_name']}' "
            f"(revenue share: {record['revenue_share_pct']}%)."
        )

    elif rights == RIGHTS_TRANSFORMED_COMMENTARY:
        if not getattr(cfg, "voiceover", False):
            # Defense in depth — validate_source_rights_args should have
            # already caught this, but cfg can be constructed directly
            # (tests, notebooks, the web API) without going through argparse.
            raise RuntimeError(
                "--source-rights transformed_commentary requires --voiceover "
                "to be enabled — the fair-use position depends on it."
            )
        # Cap how much of the original audio survives — less of the
        # source used is one of the four fair-use factors in its favor.
        cap = 0.12
        if getattr(cfg, "original_volume", 0.15) > cap:
            print(
                f"   ℹ️  source-rights=transformed_commentary: clamping "
                f"--original-volume {cfg.original_volume} -> {cap} "
                "(minimizing surviving original audio strengthens the "
                "fair-use position)."
            )
            cfg.original_volume = cap

    elif rights == RIGHTS_UNKNOWN:
        print(
            "   ⚠️  source-rights=unknown — proceeding because this is a "
            "manually-driven run. An unattended/scheduled pipeline must "
            "refuse to auto-publish anything in this bucket."
        )


def build_attribution_source_url(cfg, source_info: SourceInfo) -> Optional[str]:
    """
    Build the string clipping.metadata._build_youtube_description() will
    render as "Source: {this}" in the generated description. Returns None
    where no attribution is owed or possible.
    """
    rights = getattr(cfg, "source_rights", RIGHTS_UNKNOWN)
    uploader = source_info.get("uploader")
    url = source_info.get("webpage_url")

    if rights in (RIGHTS_LICENSED_CC, RIGHTS_PERMISSIONED) and url:
        return f"{uploader} — {url}" if uploader else url

    if rights == RIGHTS_TRANSFORMED_COMMENTARY and url:
        label = f"Commentary on original video by {uploader}" if uploader else "Commentary on original video"
        return f"{label} — {url}"

    return None

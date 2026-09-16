#!/usr/bin/env python3
"""
autopilot.py — One command: clip, then (optionally) upload.

Replaces running main.py, then run_upload.py, then run_fb_upload.py by hand
as three separate manual steps — P0 from the automation blueprint. Doesn't
change any of them: this is a thin dispatcher on top of the same
clipping.runner.run_pipeline() and upload_manifest_to_*() functions those
scripts already call.

Usage:
    # Just clip (identical to `python main.py ...`)
    python autopilot.py --url "https://youtube.com/watch?v=..." --clips 3

    # Clip, then upload the results to YouTube
    python autopilot.py --url "..." --clips 3 --upload-youtube

    # Clip, then upload to both platforms
    python autopilot.py --url "..." --clips 3 --upload-youtube --upload-facebook

    # Skip clipping — just run the upload stage(s) against an existing manifest
    python autopilot.py --skip-clip --upload-youtube --manifest-file outputs/render_manifest.json

All clipping flags (--url, --clips, --source-rights, --voiceover, etc.) are
main.py's own — this script doesn't redefine them, it forwards whatever it
doesn't recognize straight to clipping.config.build_config(). Run
`python main.py --help` for that full list. Flags below are this script's:
the upload-stage configuration that used to live in run_upload.py /
run_fb_upload.py.

Story mode and batch mode aren't wired into the upload stage yet — they
don't produce the single render_manifest.json the uploaders expect. Use
--upload-youtube/--upload-facebook only with the normal single-URL mode.
"""

from __future__ import annotations

import argparse
import os
import sys


def _build_orchestrator_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="🎬 OpenSource Clipping — Autopilot (clip -> upload, one command)",
        epilog=(
            "Unrecognized flags are forwarded to the clipping pipeline — "
            "run `python main.py --help` for the full clipping option list."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--with-hook", action="store_true",
        help="Keep the hook glitch teaser (autopilot defaults to a uniform clip, i.e. --no-hook, "
        "since the fallback glitch transition was found to leave an audible gap — see clipping/studio/effects.py).",
    )
    p.add_argument(
        "--skip-clip", action="store_true",
        help="Skip clipping entirely and just run the upload stage(s) against an existing manifest.",
    )
    p.add_argument(
        "--manifest-file", default=None,
        help="Manifest path for the upload stage. Default: <outputs_dir>/render_manifest.json "
        "from the clipping stage just run, or 'outputs/render_manifest.json' if --skip-clip.",
    )

    yt = p.add_argument_group("YouTube upload")
    yt.add_argument("--upload-youtube", action="store_true", help="Upload results to YouTube after clipping.")
    yt.add_argument("--youtube-token-file", default=".credentials/youtube_token.json")
    yt.add_argument("--youtube-tz-name", default="Asia/Makassar")
    yt.add_argument("--youtube-interval-hours", type=int, default=24)
    yt.add_argument("--youtube-start-local", default=None)
    yt.add_argument("--youtube-test-mode", action="store_true")
    yt.add_argument("--youtube-safety-config", default="upload_safety.json")
    yt.add_argument(
        "--youtube-no-approval", action="store_true",
        help="Skip manual approval prompts (risky — not recommended for channels recovering from a ban).",
    )

    fb = p.add_argument_group("Facebook upload")
    fb.add_argument("--upload-facebook", action="store_true", help="Upload results to Facebook Reels after clipping.")
    fb.add_argument("--fb-tz-name", default=os.environ.get("APP_TIMEZONE", "Asia/Makassar"))
    fb.add_argument("--fb-interval-hours", type=int, default=5)
    fb.add_argument("--fb-test-mode", action="store_true")

    return p


def _run_clip_stage(remaining_argv: list[str]) -> str:
    """Runs the same dispatch main.py does, and returns the resulting manifest path
    for normal mode (None for story/batch mode, which aren't upload-wired yet)."""
    from clipping.config import build_config

    cfg = build_config(remaining_argv)

    if not cfg.api_key_gemini:
        print("❌ ERROR: GOOGLE_API_KEY environment variable not found.")
        sys.exit(1)

    if getattr(cfg, "story_mode", False):
        from clipping.story_runner import run_story_pipeline
        print("🎬 Autopilot: Story Clip Mode (upload stage not wired for this mode — clipping only)")
        run_story_pipeline(cfg)
        return None

    if getattr(cfg, "batch_file", None):
        from clipping.phase1.input_handler import InputManager
        from clipping.phase1.batch_runner import run_batch, write_batch_report, print_batch_summary
        print("🎬 Autopilot: Batch Mode (upload stage not wired for this mode — clipping only)")
        manager = InputManager(batch_file=cfg.batch_file)
        valid_sources, _ = manager.validate_all()
        if not valid_sources:
            print("❌ No valid sources to process.")
            sys.exit(1)
        results = run_batch(cfg, valid_sources)
        write_batch_report(results, os.path.join(cfg.outputs_dir, "batch_report.json"))
        print_batch_summary(results)
        return None

    from clipping.runner import run_pipeline
    print(f"🎬 Autopilot: Clipping {cfg.source_url}")
    run_pipeline(cfg)
    return os.path.join(cfg.outputs_dir, "render_manifest.json")


def _run_youtube_upload(args, manifest_path: str) -> None:
    from youtube_uploader import upload_manifest_to_youtube
    from youtube_uploader.safety import load_safety_config

    if not os.path.exists(args.youtube_token_file):
        print(f"⏭️  Skipping YouTube upload — token not found at '{args.youtube_token_file}'.")
        return

    out_dir = os.path.dirname(manifest_path) or "."
    if args.youtube_no_approval:
        print("⚠️  YouTube: manual approval disabled (--youtube-no-approval). Uploading without confirmation.")

    upload_manifest_to_youtube(
        token_file=args.youtube_token_file,
        manifest_file=manifest_path,
        result_file=os.path.join(out_dir, "youtube_upload_results.json"),
        updated_manifest_file=os.path.join(out_dir, "render_manifest_uploaded.json"),
        tz_name=args.youtube_tz_name,
        interval_hours=args.youtube_interval_hours,
        start_local=args.youtube_start_local,
        test_mode=args.youtube_test_mode,
        safety_config=load_safety_config(args.youtube_safety_config),
        skip_approval=args.youtube_no_approval,
    )


def _run_facebook_upload(args, manifest_path: str) -> None:
    from facebook_uploader import upload_manifest_to_facebook

    if not os.environ.get("META_PAGE_ACCESS_TOKEN") or not os.environ.get("META_PAGE_ID"):
        print("⏭️  Skipping Facebook upload — META_PAGE_ACCESS_TOKEN / META_PAGE_ID not set.")
        return

    out_dir = os.path.dirname(manifest_path) or "."
    upload_manifest_to_facebook(
        manifest_file=manifest_path,
        result_file=os.path.join(out_dir, "fb_upload_results.json"),
        updated_manifest_file=os.path.join(out_dir, "render_manifest_fb_uploaded.json"),
        tz_name=args.fb_tz_name,
        interval_hours=args.fb_interval_hours,
        test_mode=args.fb_test_mode,
    )


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    orchestrator_parser = _build_orchestrator_parser()
    args, remaining_argv = orchestrator_parser.parse_known_args()

    if not args.with_hook and "--no-hook" not in remaining_argv:
        remaining_argv = remaining_argv + ["--no-hook"]

    print("=" * 70)
    print("🚀 OpenSource Clipping — Autopilot")
    print("=" * 70)

    manifest_path = args.manifest_file
    if not args.skip_clip:
        clip_manifest = _run_clip_stage(remaining_argv)
        manifest_path = manifest_path or clip_manifest
        if manifest_path is None and (args.upload_youtube or args.upload_facebook):
            print("⚠️  Story/batch mode doesn't produce a single manifest — skipping upload stage(s).")
            manifest_path = None
    else:
        manifest_path = manifest_path or "outputs/render_manifest.json"
        if remaining_argv:
            print(f"⚠️  --skip-clip set — ignoring clipping-only flags: {remaining_argv}")

    if manifest_path and not os.path.exists(manifest_path) and (args.upload_youtube or args.upload_facebook):
        print(f"❌ Manifest not found at '{manifest_path}' — cannot upload.")
        sys.exit(1)

    if manifest_path:
        if args.upload_youtube:
            _run_youtube_upload(args, manifest_path)
        if args.upload_facebook:
            _run_facebook_upload(args, manifest_path)

    print("\n✅ Autopilot complete.")


if __name__ == "__main__":
    main()

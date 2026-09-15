#!/usr/bin/env python3
"""
OpenSource Clipping — AI Auto-Clipper & Teaser Generator

Usage:
    python main.py --url "https://..."      # run with required URL
    python main.py --url "https://..." --clips 5 --ratio 16:9
    python main.py --help                   # show all available options
"""

import sys

from clipping.config import build_config


def main():
    cfg = build_config(sys.argv[1:])

    version = "1.12.0"

    # ── Story Clip Mode ──────────────────────────────────────────────
    if getattr(cfg, "story_mode", False):
        from clipping.story_runner import run_story_pipeline

        print("=" * 70)
        print(f"🎬 OpenSource Clipping v{version} — Story Clip Mode")
        print("=" * 70)
        print(f"   Recipe      : {cfg.story_recipe_path}")
        print(f"   Sources     : {cfg.sources_json_path}")
        print(f"   Rasio       : {cfg.pilihan_rasio}")
        print(f"   Output Dir  : {cfg.story_output_dir}")
        print(f"   Skip DL     : {'YES' if cfg.skip_download else 'NO'}")
        print("=" * 70)

        run_story_pipeline(cfg)

        print("\n✅ Selesai! Semua story clips telah dirender.")
        return

    # ── Batch Mode ───────────────────────────────────────────────────
    if getattr(cfg, "batch_file", None):
        import os
        from clipping.phase1.input_handler import InputManager
        from clipping.phase1.batch_runner import run_batch, write_batch_report, print_batch_summary

        if not cfg.api_key_gemini:
            print("❌ ERROR: GOOGLE_API_KEY environment variable tidak ditemukan.")
            print("   Set via: export GOOGLE_API_KEY='your-key' atau buat file .env")
            sys.exit(1)

        print("=" * 70)
        print(f"🎬 OpenSource Clipping v{version} — Batch Mode")
        print("=" * 70)
        print(f"   Batch File  : {cfg.batch_file}")

        manager = InputManager(batch_file=cfg.batch_file)
        valid_sources, invalid_sources = manager.validate_all()

        print(f"   Total items : {manager.count()}")
        print(f"   Valid       : {len(valid_sources)}")
        print(f"   Invalid     : {len(invalid_sources)}")
        if invalid_sources:
            for src, err in invalid_sources:
                print(f"     ✗ {src.source}: {err}")
        print("=" * 70)

        if not valid_sources:
            print("❌ No valid sources to process.")
            sys.exit(1)

        results = run_batch(cfg, valid_sources)

        report_path = os.path.join(cfg.outputs_dir, "batch_report.json")
        write_batch_report(results, report_path)
        print(f"\n💾 Batch report saved to {report_path}")
        print_batch_summary(results)
        return

    # ── Normal Auto-Clip Mode ────────────────────────────────────────
    # Lazy import so --help works without heavy deps
    from clipping.runner import run_pipeline

    if not cfg.api_key_gemini:
        print("❌ ERROR: GOOGLE_API_KEY environment variable tidak ditemukan.")
        print("   Set via: export GOOGLE_API_KEY='your-key' atau buat file .env")
        sys.exit(1)

    _PLATFORM_LABELS = {
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "gdrive": "Google Drive",
    }
    platform_key = getattr(cfg, "source_platform", "youtube")
    platform_label = _PLATFORM_LABELS.get(platform_key, platform_key)
    
    print("=" * 70)
    print(f"🎬 OpenSource Clipping v{version}")
    print("=" * 70)
    print(f"   Source      : {platform_label}")
    print(f"   URL         : {cfg.url_youtube}")
    print(f"   Jumlah Clip : {cfg.jumlah_clip}")
    print(f"   Rasio       : {cfg.pilihan_rasio}")
    print(f"   Font Style  : {cfg.gaya_font_aktif}")
    print(f"   Subtitles   : {'OFF' if cfg.no_subs else 'ON'}")
    print(f"   B-Roll      : {'ON' if cfg.use_broll else 'OFF'}")
    print(f"   Hook Glitch : {'ON' if cfg.use_hook_glitch else 'OFF'}")
    print(f"   BGM         : {'ON' if cfg.use_auto_bgm else 'OFF'}")
    print(f"   Karaoke     : {'ON' if cfg.use_karaoke_effect else 'OFF'}")
    print(f"   Split-Screen: {'ON' if cfg.use_split_screen else 'OFF'}")
    if cfg.use_split_screen:
        print(f"   Dynamic Split: {'ON' if cfg.use_dynamic_split else 'OFF'}")
        print(f"   Split Trigger: {cfg.split_trigger}")
    print(f"   Whisper     : {cfg.whisper_model} ({cfg.whisper_device})")
    print(f"   Gemini      : {cfg.gemini_model}")
    print(
        f"   Monetization: {'ON' if cfg.enable_monetization_scoring else 'OFF'} "
        f"(Q:{cfg.monetization_quality_weight} / M:{cfg.monetization_weight})"
    )
    if getattr(cfg, "watermark_enabled", False):
        wm_type = "Text" if cfg.watermark_text else "Image"
        wm_content = cfg.watermark_text or cfg.watermark_image or "-"
        print(f"   Watermark   : ON ({wm_type}: {wm_content})")
        print(f"   WM Opacity  : {cfg.watermark_opacity}%")
        print(f"   WM Position : {cfg.watermark_position}")
        print(f"   WM Padding  : {cfg.watermark_padding}px")
        if cfg.watermark_image:
            print(f"   WM Scale    : {getattr(cfg, 'watermark_scale', 15)}% of frame height")
    print("=" * 70)

    run_pipeline(cfg)

    print("\n✅ Selesai! Semua klip telah dirender.")


if __name__ == "__main__":
    main()

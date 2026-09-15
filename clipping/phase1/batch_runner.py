"""
Batch Runner — runs the full clipping pipeline once per input source.

Wires clipping.phase1.input_handler (multi-source loading/validation) into
clipping.runner.run_pipeline (single-video pipeline) without modifying that
function. Each source gets its own isolated outputs_dir and
file_video_asli path so concurrent/sequential batch items never collide on
checkpoint state, downloaded video files, or rendered clip filenames.
"""

import copy
import json
import os
import re
from typing import List, Dict

from .input_handler import InputSource, InputManager


def slugify_source(source: InputSource, index: int) -> str:
    """
    Build a filesystem-safe, human-recognizable directory name for a batch item.

    Prefers the source's title if present, falls back to a truncated form of
    the URL/path, always prefixed with the batch index to guarantee uniqueness
    even if two sources produce the same slug.
    """
    basis = source.title or source.source
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", basis).strip("_").lower()
    slug = slug[:50] if slug else "item"
    return f"{index:03d}_{slug}"


def build_item_config(base_cfg, source: InputSource, index: int):
    """
    Derive a per-source config from base_cfg, isolating outputs_dir and
    file_video_asli so this batch item cannot collide with any other.

    Shared/global resources (fonts, BGM assets, base_dir) are intentionally
    left pointing at the same paths as base_cfg — those are safe to share.
    """
    cfg = copy.copy(base_cfg)

    item_dir = os.path.join(base_cfg.outputs_dir, "batch", slugify_source(source, index))
    os.makedirs(item_dir, exist_ok=True)

    cfg.outputs_dir = item_dir
    cfg.file_video_asli = os.path.join(item_dir, "video_asli.mp4")
    cfg.url_youtube = source.source

    if source.source_type in ("youtube", "tiktok", "instagram"):
        cfg.source_platform = source.source_type
    elif source.source_type == "local_file":
        # local_file sources have nothing to download. Point file_video_asli
        # AT the local file directly, and pre-seed THIS item's checkpoint
        # (freshly created per-item, so it has no prior "download" record)
        # so run_pipeline's Step 1 skip-check finds it already complete and
        # never calls engine.download_video (which has no local-file path).
        cfg.file_video_asli = os.path.abspath(source.source)
        if getattr(cfg, "enable_checkpoint", True):
            from .checkpoint import CheckpointManager

            item_checkpoint = CheckpointManager(cfg.outputs_dir)
            item_checkpoint.mark_step_complete("download", {"file": cfg.file_video_asli})

    return cfg


def run_batch(base_cfg, sources: List[InputSource]) -> List[Dict]:
    """
    Run the full pipeline once per source.

    A failure in one item is caught and recorded — it does not abort the
    remaining batch items.

    Args:
        base_cfg: The base SimpleNamespace config (from build_config()).
        sources: List of InputSource to process.

    Returns:
        List of per-item result dicts: {source, status, outputs_dir, clips|error}
    """
    from ..runner import run_pipeline

    results = []
    total = len(sources)

    for index, source in enumerate(sources, start=1):
        print(f"\n{'=' * 70}")
        print(f"🎬 Batch {index}/{total}: {source.source}")
        print(f"{'=' * 70}")

        item_cfg = build_item_config(base_cfg, source, index)

        try:
            manifest = run_pipeline(item_cfg)
            results.append({
                "source": source.source,
                "title": source.title,
                "status": "success",
                "outputs_dir": item_cfg.outputs_dir,
                "clips_rendered": len(manifest),
            })
        except Exception as e:
            print(f"❌ Batch item {index}/{total} failed: {e}")
            results.append({
                "source": source.source,
                "title": source.title,
                "status": "failed",
                "outputs_dir": item_cfg.outputs_dir,
                "error": str(e),
            })

    return results


def write_batch_report(results: List[Dict], path: str) -> None:
    """Save the batch run summary as inspectable JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def print_batch_summary(results: List[Dict]) -> None:
    """Pretty-print a batch run summary."""
    total = len(results)
    succeeded = sum(1 for r in results if r["status"] == "success")
    failed = total - succeeded

    print("\n" + "=" * 70)
    print("📊 Batch Summary")
    print("=" * 70)
    print(f"Total: {total}  |  Succeeded: {succeeded}  |  Failed: {failed}")

    for r in results:
        icon = "✅" if r["status"] == "success" else "❌"
        detail = f"{r.get('clips_rendered', 0)} clips" if r["status"] == "success" else r.get("error", "")
        print(f"  {icon} {r['source']} — {detail}")

    print("=" * 70)

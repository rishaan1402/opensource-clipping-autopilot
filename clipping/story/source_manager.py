"""
clipping.story.source_manager — Multi-Source Download & Cache Manager

Handles downloading videos from multiple platforms (YouTube, TikTok,
Instagram, Google Drive) and caching them locally for reuse across
the Story Clip pipeline.

Note: Engine functions are imported lazily to avoid pulling in heavy
dependencies (faster_whisper, yt_dlp) at module level.
"""

import os
import shutil


# ==============================================================================
# CACHE DIRECTORY
# ==============================================================================

def get_cache_dir(outputs_dir: str) -> str:
    """Return (and create) the story source cache directory."""
    cache_dir = os.path.join(outputs_dir, "story_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


# ==============================================================================
# SINGLE SOURCE DOWNLOAD
# ==============================================================================

def _download_single_source(
    source: dict,
    cache_dir: str,
    download_source_height: str | int = "max",
) -> str:
    """
    Download a single source video and cache it.

    Parameters
    ----------
    source : dict
        A source entry from ``sources.json`` (must have ``id``, ``platform``,
        ``url`` or ``local_path``).
    cache_dir : str
        Directory to cache downloaded files.
    download_source_height : str | int
        Desired download resolution (passed to ``engine.download_video``).

    Returns
    -------
    str
        Absolute path to the cached (or local) video file.

    Raises
    ------
    RuntimeError
        If download fails.
    """
    sid = source["id"]
    platform = source["platform"]
    cached_path = os.path.join(cache_dir, f"{sid}.mp4")

    # --- Skip if already cached ---
    if os.path.exists(cached_path):
        size_mb = os.path.getsize(cached_path) / (1024 * 1024)
        print(f"   ⏩ '{sid}' sudah ada di cache ({size_mb:.1f} MB), skip download.")
        return cached_path

    # --- Local file: copy to cache ---
    if platform == "local":
        local_path = source["local_path"]
        print(f"   📁 [{sid}] Menyalin file lokal: {local_path}")
        shutil.copy2(local_path, cached_path)
        print(f"   ✅ '{sid}' berhasil disalin ke cache.")
        return cached_path

    # --- Remote: download using engine ---
    url = source["url"]
    print(f"   📥 [{sid}] Mendownload dari {platform}: {url}")

    # Lazy import to avoid pulling in heavy deps (faster_whisper, yt_dlp)
    from .. import engine

    engine.download_video(
        url=url,
        output_path=cached_path,
        use_dlp_subs=False,  # No subtitle download for story sources
        download_source_height=download_source_height,
        source_platform=platform,
    )

    if not os.path.exists(cached_path):
        raise RuntimeError(
            f"❌ Download gagal untuk source '{sid}' — "
            f"file tidak ditemukan di {cached_path}"
        )

    size_mb = os.path.getsize(cached_path) / (1024 * 1024)
    print(f"   ✅ '{sid}' berhasil didownload ({size_mb:.1f} MB)")
    return cached_path


# ==============================================================================
# BATCH DOWNLOAD ALL SOURCES
# ==============================================================================

def download_all_sources(
    source_registry: dict[str, dict],
    cache_dir: str,
    download_source_height: str | int = "max",
) -> dict[str, str]:
    """
    Download all sources listed in the registry.

    Parameters
    ----------
    source_registry : dict
        Mapping of source_id → source entry dict.
    cache_dir : str
        Directory to cache downloaded files.
    download_source_height : str | int
        Desired download resolution.

    Returns
    -------
    dict[str, str]
        Mapping of source_id → cached file path.
    """
    total = len(source_registry)
    print(f"\n📦 Mendownload {total} sumber video...\n")

    paths: dict[str, str] = {}
    failed: list[str] = []

    for idx, (sid, source) in enumerate(source_registry.items(), 1):
        print(f"[{idx}/{total}] Source: {source.get('name', sid)}")
        try:
            path = _download_single_source(
                source, cache_dir, download_source_height
            )
            paths[sid] = path
        except Exception as e:
            print(f"   ⚠️ GAGAL download '{sid}': {e}")
            failed.append(sid)

    # --- Summary ---
    print(f"\n{'='*50}")
    print(f"📦 Download Summary: {len(paths)}/{total} berhasil")
    if failed:
        print(f"   ❌ Gagal: {', '.join(failed)}")
    print(f"{'='*50}\n")

    return paths


# ==============================================================================
# STATUS SAVER
# ==============================================================================

def save_sources_status(
    source_registry: dict[str, dict],
    cached_paths: dict[str, str],
    outputs_dir: str,
) -> str:
    """
    Save a ``sources_status.json`` file documenting download results.

    Returns the path to the saved file.
    """
    import json

    status_entries = []
    for sid, src in source_registry.items():
        entry = {
            "id": sid,
            "name": src.get("name", sid),
            "platform": src["platform"],
            "url": src.get("url"),
            "local_path": src.get("local_path"),
            "cached_path": cached_paths.get(sid),
            "status": "ok" if sid in cached_paths else "failed",
        }
        if sid in cached_paths and os.path.exists(cached_paths[sid]):
            entry["size_mb"] = round(
                os.path.getsize(cached_paths[sid]) / (1024 * 1024), 2
            )
        status_entries.append(entry)

    status_path = os.path.join(outputs_dir, "sources_status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump({"sources": status_entries}, f, indent=2, ensure_ascii=False)

    print(f"💾 Sources status disimpan ke: {status_path}")
    return status_path

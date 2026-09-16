"""
clipping.metadata — QA Metadata Preview & Normalization

Maps to the QA Metadata Preview cell in the notebook.
"""

import json


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _normalize_spaces(text):
    return " ".join(str(text or "").split()).strip()


def _trim_title(text, max_len=100):
    text = _normalize_spaces(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].strip()
    return cut if cut else text[:max_len].strip()


def _normalize_hashtags(text, min_tags=2, max_tags=3):
    parts = _normalize_spaces(text).split()
    clean = []
    seen = set()

    for p in parts:
        if not p:
            continue
        if not p.startswith("#"):
            p = "#" + p.lstrip("#")
        key = p.lower()
        if key not in seen:
            seen.add(key)
            clean.append(p)
        if len(clean) >= max_tags:
            break

    return " ".join(clean), len(clean)


def _normalize_keyword_tags(tags, min_items=5, max_items=8):
    if not isinstance(tags, list):
        tags = []
    out = []
    seen = set()

    for t in tags:
        x = _normalize_spaces(t)
        if not x:
            continue
        key = x.lower()
        if key not in seen:
            seen.add(key)
            out.append(x)
        if len(out) >= max_items:
            break

    return out


def _build_youtube_description(hook, context, hashtags, source_url=None):
    parts = [
        _normalize_spaces(hook),
        _normalize_spaces(context),
        _normalize_spaces(hashtags),
    ]
    desc = "\n\n".join([p for p in parts if p]).strip()

    # Auto-add source attribution if available
    if source_url:
        desc += f"\n\nSource: {source_url}"

    return desc


def _build_tiktok_caption(caption, hashtags):
    caption = _normalize_spaces(caption)
    hashtags = _normalize_spaces(hashtags)
    if caption and hashtags:
        return f"{caption}\n{hashtags}"
    return caption or hashtags


def _looks_indonesian(text):
    """Checks for common Indonesian stopwords — used to flag when a field that's
    supposed to be English-only (title_en, hashtags, etc.) accidentally contains
    Indonesian text. The words below are the actual Indonesian terms being
    matched against, not text to translate."""
    text = f" {_normalize_spaces(text).lower()} "
    indicators = [
        " yang ", " dan ", " untuk ", " dengan ", " karena ", " adalah ",
        " bisa ", " tidak ", " lebih ", " dalam ", " pada ", " agar ",
        " dari ", " ini ", " itu ", " juga ", " kalau ", " saat ",
        " tentang ", " bikin ", " banget ", " jadi ", " sudah ",
    ]
    return any(w in text for w in indicators)


# ==============================================================================
# MAIN API
# ==============================================================================

def normalize_and_validate(result_json: list[dict]) -> list[dict]:
    """
    Normalize and enrich metadata fields, add *_final fields.

    Mutates items in-place and returns sorted list.
    """
    valid_items = []
    report = []
    all_warnings = []
    for item in result_json:
        if not isinstance(item, dict):
            print(f"⚠️ Skipping invalid metadata item (not a dict): {type(item)}")
            continue

        # 1. FLATTENING: If model put everything in a "metadata" key, bring it up
        if isinstance(item.get("metadata"), dict):
            for k, v in item["metadata"].items():
                if k not in item:
                    item[k] = v

        # 2. ALIASING: Handle variations in field names (especially for non-Gemini providers)
        rank = item.get("rank") or item.get("peringkat") or item.get("no") or "?"
        item["rank"] = rank
        item["viral_score"] = item.get("viral_score", 0)
        
        # Timing aliases
        it_st = item.get("start_time") or item.get("timing_klip_start") or item.get("clip_start") or item.get("start")
        it_en = item.get("end_time") or item.get("timing_klip_end") or item.get("clip_end") or item.get("end")
        item["start_time"] = float(it_st) if it_st is not None else 0.0
        item["end_time"] = float(it_en) if it_en is not None else 0.0

        # Hook aliases (DeepSeek sometimes returns hook as string + hook_start_time at root)
        if isinstance(item.get("hook"), str) and "hook_start_time" in item:
            item["hook"] = {
                "text": item["hook"],
                "start_time": item.get("hook_start_time", item["start_time"]),
                "end_time": item.get("hook_end_time", item["end_time"]),
            }
        
        # Ensure hook exists as dict for later code
        if not isinstance(item.get("hook"), dict):
            item["hook"] = {"text": str(item.get("hook", "")), "start_time": item["start_time"], "end_time": item["start_time"] + 3.0}

        item["title_id"] = _trim_title(item.get("title_id", ""))
        item["title_en"] = _trim_title(item.get("title_en", ""))
        item["description_hook"] = _normalize_spaces(item.get("description_hook", ""))
        item["description_context"] = _normalize_spaces(item.get("description_context", ""))
        item["hashtags"] = _normalize_spaces(item.get("hashtags") or item.get("hashtag") or "")
        item["tiktok_title_id"] = _normalize_spaces(item.get("tiktok_title_id", ""))
        item["tiktok_caption_id"] = _normalize_spaces(item.get("tiktok_caption_id", ""))
        item["tiktok_caption"] = _normalize_spaces(item.get("tiktok_caption", ""))
        item["keyword_tags"] = _normalize_keyword_tags(item.get("keyword_tags", []))

        hastag_clean, hashtag_count = _normalize_hashtags(item["hashtags"])
        item["hashtags"] = hastag_clean

        # Enriched fields
        item["youtube_title_final"] = item["title_en"]
        item["youtube_description_final"] = _build_youtube_description(
            item.get("description_hook", ""),
            item.get("description_context", ""),
            item.get("hashtags", ""),
            source_url=item.get("source_url"),
        )
        item["youtube_tags_final"] = item.get("keyword_tags", [])

        # TikTok EN (existing behavior)
        item["tiktok_caption_final"] = _build_tiktok_caption(
            item.get("tiktok_caption", ""),
            item.get("hashtags", ""),
        )

        # TikTok ID (new fields)
        item["tiktok_title_id_final"] = item.get("tiktok_title_id", "") or item.get("title_id", "")
        item["tiktok_caption_id_final"] = _build_tiktok_caption(
            item.get("tiktok_caption_id", ""),
            item.get("hashtags", ""),
        )

        # --- Warnings ---
        warning = []
        if not item["title_id"]:
            warning.append("title_id empty")
        if len(item["title_id"]) > 100:
            warning.append("title_id > 100 characters")

        if not item["title_en"]:
            warning.append("title_en empty")
        if len(item["title_en"]) > 100:
            warning.append("title_en > 100 characters")

        if hashtag_count < 2 or hashtag_count > 3:
            warning.append("hashtag count not 2-3")

        if not item["description_hook"]:
            warning.append("description_hook empty")
        if not item["description_context"]:
            warning.append("description_context empty")
        if len(item["keyword_tags"]) < 5:
            warning.append("keyword_tags too few")

        if not item["tiktok_title_id"]:
            warning.append("tiktok_title_id empty")
        if not item["tiktok_caption_id"]:
            warning.append("tiktok_caption_id empty")
        if not item["tiktok_caption"]:
            warning.append("tiktok_caption empty")

        # Safety: warn if description is too short (looks like spam/lazy reupload)
        yt_desc = item.get("youtube_description_final", "")
        if len(yt_desc) < 30:
            warning.append("youtube_description too short (< 30 chars) — looks like spam")

        if _looks_indonesian(item["title_en"]):
            warning.append("title_en detected as not fully English")
        if _looks_indonesian(item["description_hook"]):
            warning.append("description_hook detected as not fully English")
        if _looks_indonesian(item["description_context"]):
            warning.append("description_context detected as not fully English")
        if _looks_indonesian(item["tiktok_caption"]):
            warning.append("tiktok_caption detected as not fully English")

        if item["tiktok_title_id"] and not _looks_indonesian(item["tiktok_title_id"]):
            warning.append("tiktok_title_id detected as not Indonesian")
        if item["tiktok_caption_id"] and not _looks_indonesian(item["tiktok_caption_id"]):
            warning.append("tiktok_caption_id detected as not Indonesian")

        if warning:
            all_warnings.append((rank, warning))
            
        item["_warnings_temp"] = " | ".join(warning) if warning else "OK"
        valid_items.append(item)

    # Sort based on viral_score (descending)
    valid_items = sorted(valid_items, key=lambda x: x.get("viral_score", 0), reverse=True)
    
    # Re-assign rank to be purely sequential and build report
    for idx, item in enumerate(valid_items):
        item["rank"] = idx + 1
        classification = item.get("account_classification", {})
        
        report.append({
            "rank": item["rank"],
            "viral_score": item.get("viral_score", 0),
            "duration": round(float(item.get("end_time", 0)) - float(item.get("start_time", 0)), 2),
            "target_account": classification.get("target_account", ""),
            "title_id": item["title_id"],
            "title_en": item["title_en"],
            "tiktok_title_id": item["tiktok_title_id"],
            "hashtags": item["hashtags"],
            "warnings": item.pop("_warnings_temp", "OK"),
        })

    return valid_items


def print_preview(result_json: list[dict]) -> None:
    """Print a human-readable metadata preview to stdout."""
    print("✅ Metadata preview ready.")
    print("Additional fields created:")
    print("- youtube_title_final")
    print("- youtube_description_final")
    print("- youtube_tags_final")
    print("- tiktok_caption_final")
    print("- tiktok_title_id_final")
    print("- tiktok_caption_id_final")
    print()

    print("===== PER-CLIP DETAIL PREVIEW =====")
    for item in result_json:
        classification = item.get("account_classification", {})
        print(f"\n--- Rank {item['rank']} (Viral Score: {item.get('viral_score', '?')}) ---")
        print(f"Target Account    : {classification.get('target_account', '')} ({classification.get('account_type', '')})")
        print(f"Account Reason    : {classification.get('reason', '')}")
        print(f"Title ID          : {item['title_id']}")
        print(f"Title EN          : {item['title_en']}")
        print(f"TikTok Title ID   : {item.get('tiktok_title_id_final', '')}")
        print(f"Hashtag           : {item['hashtags']}")
        print(f"Hook Desc         : {item['description_hook']}")
        print(f"Ctx Desc          : {item['description_context']}")
        print(f"YT Desc           : {item['youtube_description_final']}")
        print(f"YT Tags           : {item['youtube_tags_final']}")
        print(f"TikTok EN         : {item['tiktok_caption_final']}")
        print(f"TikTok Caption ID : {item.get('tiktok_caption_id_final', '')}")


def save_metadata_preview(result_json: list[dict], path: str = "metadata_preview.json") -> None:
    """Save normalized metadata to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Disimpan ke {path}")
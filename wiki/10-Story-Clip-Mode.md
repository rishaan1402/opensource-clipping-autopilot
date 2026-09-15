# 🎬 Story Clip Mode

Story Clip is a multi-source narrative assembly pipeline designed for campaigns (e.g., brand briefs) where you need to take specific scenes from various video sources and combine them into a cohesive story.

---

## Overview

Unlike the standard auto-clipping mode (which uses AI to find highlights), Story Clip mode lets you **manually define** exactly which scenes to use, from which videos, and in what order.

### Key Advantages

1. **Multi-Source** — Combine segments from YouTube, TikTok, Instagram, Google Drive, or local files
2. **Automatic Normalization** — Different resolutions and FPS are normalized seamlessly
3. **Hook + Highlight** — Each clip generates two separate outputs: a teaser hook and the main content
4. **Auto-Transcription** — Whisper transcription runs automatically and is cached for reference
5. **Clean Output** — Videos are produced without subtitles or text overlays by default
6. **Idempotent Downloads** — Already-downloaded files are never re-downloaded

---

## How to Run

```bash
python main.py --story-mode \
  --story-recipe story_recipe.json \
  --sources-json sources.json
```

### Additional Flags

| Flag | Description |
|---|---|
| `--skip-download` | Skip downloads if all source videos are already cached |
| `--story-output-dir` | Custom output directory (default: `outputs/story_clips`) |
| `--ratio` | Override the global render ratio (default from recipe) |

---

## Pipeline Flow

```
1. Load Sources (sources.json)
   ↓
2. Download & Cache (outputs/story_cache/)
   ↓
3. Transcribe (Faster-Whisper → cached transcripts)
   ↓
4. Load Recipe (story_recipe.json)
   ↓
5. Assembly (FFmpeg trim → normalize → concat)
   ↓
6. Output Manifest (story_manifest.json)
```

---

## `sources.json` — Video Source Registry

Register all raw video sources here. Each source needs an `id`, `name`, `url`, and `platform`.

### Supported Platforms

| Platform | Value |
|---|---|
| YouTube | `youtube` |
| TikTok | `tiktok` |
| Instagram | `instagram` |
| Google Drive | `gdrive` |
| Local File | `local` |

### Example

```json
{
  "$schema": "sources_v1",
  "sources": [
    {
      "id": "speaker_a",
      "name": "Speaker A — Main Interview",
      "url": "https://www.youtube.com/watch?v=ABC123",
      "platform": "youtube"
    },
    {
      "id": "broll_city",
      "name": "City B-Roll Stock",
      "url": "https://www.tiktok.com/@user/video/1234567890",
      "platform": "tiktok"
    },
    {
      "id": "local_intro",
      "name": "Custom Intro Animation",
      "url": "/path/to/intro.mp4",
      "platform": "local"
    }
  ]
}
```

---

## `story_recipe.json` — Clip Assembly Recipe

This file is your digital director. Define the exact sequence of scenes for each clip.

### Structure

```json
{
  "$schema": "story_recipe_v1",
  "project_name": "Campaign Name",
  "default_settings": {
    "ratio": "9:16"
  },
  "clips": [
    {
      "clip_id": 1,
      "title": "Clip Title",
      "hook": {
        "scenes": [
          {
            "source_id": "speaker_a",
            "start": 0.0,
            "end": 5.0,
            "label": "Attention-grabbing quote"
          }
        ]
      },
      "highlight": {
        "scenes": [
          {
            "source_id": "speaker_a",
            "start": 30.0,
            "end": 45.0,
            "label": "Main content section"
          },
          {
            "source_id": "broll_city",
            "start": 2.0,
            "end": 6.0,
            "label": "City establishing shot"
          }
        ],
        "transition": "cut"
      }
    }
  ]
}
```

### Scene Fields

| Field | Required | Description |
|---|---|---|
| `source_id` | ✅ | References the `id` from `sources.json` |
| `start` | ✅ | Start time in seconds (decimal) |
| `end` | ✅ | End time in seconds (decimal) |
| `label` | ❌ | Description of the scene (for tracking) |

### Transition Types

| Type | Description |
|---|---|
| `cut` | Hard cut between scenes |
| `smooth` / `crossfade` | 0.5 second dissolve transition |

---

## Output Structure

```text
outputs/
├── story_cache/           # Downloaded source videos (persistent cache)
│   ├── speaker_a.mp4
│   ├── broll_city.mp4
│   └── *_transcript.json  # Whisper transcriptions
├── story_clips/           # Final assembled clips
│   ├── clip_1/
│   │   ├── hook_1.mp4     # Teaser/hook video
│   │   └── highlight_1.mp4 # Main story video
│   └── clip_2/
│       ├── hook_2.mp4
│       └── highlight_2.mp4
└── story_manifest.json    # Status report for all clips
```

---

## Workflow Tips

1. **Fast Iteration** — Since all sources are cached, if clip timing feels off, just change `start`/`end` in the recipe and re-run. No re-downloading needed.

2. **Use Labels** — Always fill in the `label` field so you can track story context without replaying raw videos.

3. **Read Transcripts** — Check the auto-generated `*_transcript.json` files in `story_cache/` to find exact timestamps for quotes and moments.

4. **Skip Downloads** — After your first run, use `--skip-download` to speed up iteration:
   ```bash
   python main.py --story-mode --skip-download --story-recipe story_recipe.json
   ```

---

## Sample Files

The repository includes sample configuration files in `example/story/`:

- `sources.sample.json` — Example source registry
- `story_recipe.sample.json` — Example recipe

---

## See Also

- [Getting Started](Getting-Started) — General setup
- [CLI Reference](CLI-Reference) — All Story Clip flags

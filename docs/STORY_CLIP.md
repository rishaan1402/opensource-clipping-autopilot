# Story Clip Mode (--story-mode)

[Bahasa Indonesia](./STORY_CLIP_ID.md)

The **Story Clip** feature is a multi-source narrative assembly pipeline specifically designed for campaigns (such as Shopee brand briefs, etc.). This feature allows you to take specific scenes from various video sources (YouTube, TikTok, Instagram, Local, Google Drive) and combine them into a complete story automatically based on time specifications.

## Advantages
1. **Multi-Source**: Can take segments from TikTok A at a certain second, TikTok B at another second, and combine them seamlessly.
2. **Automatic Normalization**: Regardless of whether the original videos have different resolutions or FPS, the engine will normalize them so there are no glitches when merged (concat).
3. **Hook and Highlight Separation**: Each defined clip will generate 2 separate video outputs:
   - `hook_N.mp4`: A teaser/hook video to grab the audience's initial attention.
   - `highlight_N.mp4`: The main story/highlight video content.
4. **Transparent Auto-Transcription (Whisper)**: When downloading all sources, this feature will automatically perform transcription using Faster-Whisper and save it in the cache folder (`outputs/story_cache/*_transcript.json`). This is very useful if you want to read the original text of the video to design scenes or hooks.
5. **Clean Output**: By default, this mode is set to produce "clean" videos (empty: without built-in subtitles, without additional text overlays in the hook) so you are free to overlay text/effects in other editing software.

## How It Works (Pipeline)
1. **Load Sources**: Reads the list of video sources from the `sources.json` file.
2. **Download & Cache**: Downloads all sources from platforms (TikTok/IG/GDrive) and saves them in `outputs/story_cache/`. The system is intelligent and idempotent (files already downloaded will not be re-downloaded).
3. **Transcription**: Transcribes the audio of each source video using Faster-Whisper.
4. **Load Recipe**: Reads scene sequence instructions (scenario) from `story_recipe.json`.
5. **Assembly**: Trims each scene using FFmpeg (`trim_scene`), normalizes FPS/Resolution, and merges them without full re-encoding (maintaining quality).
6. **Manifest**: Saves a final report in `outputs/story_manifest.json` along with a summary of the status per clip.

## How to Run

Open a terminal in the project root directory, then run the following command:

```bash
python main.py --story-mode \
  --story-recipe story_recipe.json \
  --sources-json sources.json
```

**Additional CLI Options:**
- `--skip-download`: Bypasses the connection check & download process if you are sure all raw videos are already available in the `outputs/story_cache/` folder. This significantly speeds up the assembly process when iterating on trim times.
- `--story-output-dir outputs/shopee_campaign`: Use this if you want to save the final results (MP4 clips) to a specific folder (instead of the default `outputs/story_clips/`).
- `--ratio 1:1` or `--ratio 16:9`: Optional if you want to force a global render ratio even if `story_recipe.json` has provided a default ratio of `9:16`.

## `sources.json` Format

This file is responsible for registering all raw links to be used.
- Must have `id`, `name`, `url`, and `platform` (supports `youtube`, `tiktok`, `instagram`, `gdrive`, or `local`).

**Example:**
```json
{
  "$schema": "sources_v1",
  "sources": [
    {
      "id": "velia_2",
      "name": "Velia Video 2",
      "url": "https://www.tiktok.com/@veliachristyy/video/761675...",
      "platform": "tiktok"
    }
  ]
}
```

## `story_recipe.json` Format

This file acts as your digital story scenario/director.
- Inside the `clips` array, you define `clip_id`, `title`, and the main parts: `hook` and `highlight`.
- Inside the `hook` / `highlight` sub-objects, you arrange the sequence of scenes. The `start` and `end` fields (in **seconds** decimal format) absolutely determine the time segments to be taken from the related `source_id`.

**Example:**
```json
{
  "$schema": "story_recipe_v1",
  "project_name": "Shopee Fast Delivery",
  "default_settings": {
    "ratio": "9:16"
  },
  "clips": [
    {
      "clip_id": 1,
      "title": "Shipping Speed",
      "hook": {
        "scenes": [
          {
            "source_id": "velia_2",
            "start": 0.0,
            "end": 10.0,
            "label": "Courier delivering package"
          }
        ]
      },
      "highlight": {
        "scenes": [
          {
            "source_id": "donny_2",
            "start": 3.0,
            "end": 9.0,
            "label": "Donny buys at 4 AM"
          }
        ],
        "transition": "cut"
      }
    }
  ]
}
```

## Workflow Tips
1. **Fast Time Iteration**: Since all sources are permanently cached, if the clip result feels slightly off in timing (e.g., 1 second too long), you just need to change the `start` or `end` numbers in `story_recipe.json` and run it again. This process is very efficient because there is no re-downloading.
2. **Use Labels**: Always use the `label` attribute on each `scene` item in your JSON. This makes it easier to track the story context without having to play the raw video repeatedly.

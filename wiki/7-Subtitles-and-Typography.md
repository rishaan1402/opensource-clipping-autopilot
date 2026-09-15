# 📝 Subtitles & Typography

OpenSource Clipping generates word-by-word karaoke-style subtitles using the `.ASS` subtitle format, with support for kinetic typography and multiple font presets.

---

## Subtitle System Overview

The subtitle pipeline works as follows:

1. **Transcription** — Faster-Whisper generates word-level timestamps
2. **Grouping** — Words are grouped into subtitle chunks (default: 5 words per group)
3. **ASS Generation** — `.ASS` subtitle file is created with karaoke timing
4. **Rendering** — Subtitles are burned into the video via FFmpeg

---

## Font Styles

Four preset font styles are available:

| Style | Main Font | Emphasis Font | Best For |
|---|---|---|---|
| `HORMOZI` (default) | Montserrat | Anton | Business / motivational content |
| `STORYTELLER` | Inter | Lora | Narrative / storytelling |
| `CINEMATIC` | Roboto | Bebas Neue | Film / dramatic content |
| `DEFAULT` | Montserrat Black | Montserrat Medium | General purpose |

```bash
# Use Cinematic style
python main.py --url "VIDEO_URL" --font-style CINEMATIC

# Use Storyteller style
python main.py --url "VIDEO_URL" --font-style STORYTELLER
```

> **Note:** All fonts are auto-downloaded on first run. No manual font installation is needed.

---

## Karaoke Effect

By default, subtitles use a **karaoke highlight effect** where each word lights up (changes color) as it's spoken — similar to the style popularized by Alex Hormozi and Veed.io.

```bash
# Default: karaoke highlight enabled
python main.py --url "VIDEO_URL"

# Disable karaoke (use clean text instead)
python main.py --url "VIDEO_URL" --no-karaoke

# Disable all subtitles
python main.py --url "VIDEO_URL" --no-subs
```

---

## Words Per Subtitle

Control how many words appear on screen at once:

```bash
# Default: 5 words per subtitle group
python main.py --url "VIDEO_URL" --words-per-sub 5

# Fewer words (faster reading, more subtitle changes)
python main.py --url "VIDEO_URL" --words-per-sub 3

# More words (slower reading, fewer changes)
python main.py --url "VIDEO_URL" --words-per-sub 7
```

---

## Kinetic Typography

Advanced text animation with bounce/stagger effects and word scaling:

```bash
# Enable kinetic typography on main clip
python main.py --url "VIDEO_URL" --advanced-text

# Enable kinetic typography on hook teaser only
python main.py --url "VIDEO_URL" --advanced-text-hook

# Enable on both
python main.py --url "VIDEO_URL" --advanced-text --advanced-text-hook
```

### What Kinetic Typography Does

- **Word Scaling** — Emphasis words appear larger with a bounce animation
- **Dual-Font System** — Important words use the emphasis font, regular words use the main font
- **Stagger Animation** — Words appear sequentially with slight delays

---

## Subtitle Positioning

Subtitle position is automatically adjusted based on the output aspect ratio:

| Ratio | Alignment | Margin | Font Size |
|---|---|---|---|
| `9:16` (Vertical) | Bottom-center | 450px from bottom | 90pt |
| `16:9` (Landscape) | Bottom-center | 70px from bottom | 80pt |
| Split-Screen | Centered vertically | Auto-adjusted | Scaled |

---

## Transcription Options

### Whisper Settings

```bash
# Use a smaller/faster model
python main.py --url "VIDEO_URL" --whisper-model medium

# Force CPU (if no CUDA GPU)
python main.py --url "VIDEO_URL" --whisper-device cpu

# Use int8 for lower VRAM usage
python main.py --url "VIDEO_URL" --whisper-compute-type int8

# Use float32 for Kaggle compatibility
python main.py --url "VIDEO_URL" --whisper-compute-type float32
```

### YouTube Built-in Subtitles

Skip Whisper entirely by using YouTube's own subtitles:

```bash
python main.py --url "VIDEO_URL" --use-dlp-subs
```

This can significantly speed up processing. If YouTube subtitles are not available, the system automatically falls back to Whisper.

> **Note:** `--use-dlp-subs` only works with YouTube sources. Other platforms always use Whisper.

---

## Common Combinations

```bash
# Clean video without subtitles
python main.py --url "VIDEO_URL" --no-subs

# Clean text (no karaoke highlight)
python main.py --url "VIDEO_URL" --no-karaoke

# Maximum subtitle quality
python main.py --url "VIDEO_URL" --font-style HORMOZI --words-per-sub 4 --advanced-text

# Fast processing (skip Whisper)
python main.py --url "VIDEO_URL" --use-dlp-subs --no-karaoke
```

---

## See Also

- [CLI Reference](CLI-Reference) — All subtitle-related flags
- [Video Quality & Rendering](Video-Quality-and-Rendering) — Output quality settings

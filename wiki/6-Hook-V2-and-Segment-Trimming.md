# 🎬 Hook V2 & Segment Trimming

Hook V2 and Segment Trimming are two independent features that operate on different parts of the video to maximize viewer retention.

---

## Final Video Structure

```
[Hook V2 Intro] → [MAIN CLIP] → done
   ↑                    ↑
   Rapid micro-hooks    This part is affected by Segment Trimming
   (0.5-2s × 3-4)
```

---

## Hook V2 (Multi-Hook Intro)

Hook V2 creates a **rapid-fire intro** at the beginning of the video — 3-4 short clips (0.5-2 seconds each) taken from the most punchy/controversial moments within the clip. Each piece is separated by a white flash or glitch transition.

**Goal:** Stop the viewer from scrolling within the first 3-5 seconds.

```
Example Hook V2:
  [Clip 1: "NOBODY DARES" (1s)] → ⚡flash → [Clip 2: "THEY'RE ALL WRONG" (0.8s)] → ⚡flash → [Clip 3: "HERE'S THE TRUTH" (1.2s)] → ⚡flash → [MAIN CLIP]
```

### Usage

```bash
# Enable Hook V2 (default 3 micro-hooks)
python main.py --url "VIDEO_URL" --hook-v2

# Custom: 4 micro-hooks with glitch style
python main.py --url "VIDEO_URL" --hook-v2 --hook-v2-items 4 --hook-v2-style "glitch_fast"

# Adjust flash transition duration
python main.py --url "VIDEO_URL" --hook-v2 --white-flash-duration 0.15
```

### Parameters

| Argument | Default | Description |
|---|---|---|
| `--hook-v2` | `False` | Enable Multi-Hook Intro V2 |
| `--hook-v2-items` | `3` | Number of micro-hooks (3-4 recommended) |
| `--hook-v2-style` | `controversial_fast_glitch` | Style hint for AI selection |
| `--white-flash-duration` | `0.12` | Flash transition duration (seconds) |

### How AI Picks Hook Moments

1. Gemini AI analyzes the entire clip transcript
2. Identifies the most controversial, emotional, or attention-grabbing phrases
3. Selects 3-4 micro-segments with exact timestamps
4. If AI fails to return items, the system auto-generates fallback hooks using timing division

---

## Segment Trimming

Segment Trimming applies **only** to the main clip (after the hook). AI analyzes the main clip and **removes** boring sections entirely — they're not sped up, they're **cut out**, and the good parts are stitched together seamlessly.

```
Example:
  Main clip: second 30 - 90 (60 seconds total)
  
  AI finds:
    ✅ Second 30-55 : strong content, engaging
    ❌ Second 55-58 : speaker pauses/filler (removed)
    ✅ Second 58-90 : strong punchline

  Result: segment 1 + segment 2 joined directly
  Final duration: 57 seconds (3 seconds of filler removed)
```

### Trimming Modes

| Flag | Behavior | Affected Part |
|---|---|---|
| *(default, no flag)* | AI smart-trims boring/filler sections | Main clip only |
| `--silence-trim` | AI trims aggressively — pauses >0.5s removed | Main clip only |
| `--no-segment-trim` | No trimming, full start-to-end render | Main clip only |

### Usage

```bash
# Default: AI smart-trim
python main.py --url "VIDEO_URL" --hook-v2

# Aggressive silence removal
python main.py --url "VIDEO_URL" --hook-v2 --silence-trim

# No trimming (full render)
python main.py --url "VIDEO_URL" --hook-v2 --no-segment-trim
```

---

## Hook V1 vs Hook V2

| Feature | Hook V1 (`--no-hook` to disable) | Hook V2 (`--hook-v2` to enable) |
|---|---|---|
| **Type** | Single 3-second glitch teaser | Multiple rapid micro-hooks |
| **Duration** | Fixed (configurable via `--hook-duration`) | Dynamic (AI-selected, 0.5-2s each) |
| **Transition** | TV Glitch effect | White flash / RGB glitch |
| **Independence** | Disabled by `--no-hook` | Works independently of `--no-hook` |
| **AI-Driven** | Uses first few seconds of clip | AI picks best moments |

> **Important:** `--no-hook` only disables Hook V1 (the 3-second glitch teaser). Hook V2 works independently even when `--no-hook` is active.

---

## Custom Hook Source

You can also use an external video file as a custom hook (Hook V1 only):

```bash
# Use a local .mp4 file as the hook
python main.py --url "VIDEO_URL" --hook-source "/path/to/hook.mp4" --hook-source-start 5.0 --hook-duration 4

# Use a Google Drive URL
python main.py --url "VIDEO_URL" --hook-source "DRIVE_URL" --hook-source-start 2.0
```

Custom hooks automatically skip subtitle rendering to preserve the original visual quality.

---

## Combination Examples

```bash
# Hook V2 + Default segment trimming
python main.py --url "VIDEO_URL" --hook-v2

# Hook V2 + Aggressive silence trimming + No B-roll
python main.py --url "VIDEO_URL" --hook-v2 --silence-trim --no-broll

# Hook V2 + Full render (no trimming) + Custom font
python main.py --url "VIDEO_URL" --hook-v2 --no-segment-trim --font-style CINEMATIC

# Segment trimming WITHOUT Hook V2
python main.py --url "VIDEO_URL" --silence-trim
```

---

## See Also

- [CLI Reference](CLI-Reference) — Full flag details
- [Subtitles & Typography](Subtitles-and-Typography) — Subtitle settings for hooks

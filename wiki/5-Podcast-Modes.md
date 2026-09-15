# 🎙️ Podcast Modes

OpenSource Clipping provides two intelligent rendering modes specifically designed for podcast-style videos with multiple speakers. Both modes support **3+ speakers across multiple scenes**.

---

## Overview

| Feature | `--split-screen` | `--camera-switch` |
|:---|:---|:---|
| **Visual Layout** | Split (Top-Bottom) | Full Screen (Switching) |
| **Dynamic Mode** | ✅ `--dynamic-split` (Auto-toggle) | ✅ Always Dynamic |
| **Trigger Source** | Audio or Visual | Audio Only (Diarization) |
| **Reaction Shots** | ✅ Both speakers visible | ❌ Only active speaker |
| **Requirement** | Optional `HF_TOKEN` | `HF_TOKEN` (Required) |

---

## Mode 1: Split-Screen (`--split-screen`)

Divides the screen into panels to show multiple speakers simultaneously.

```
┌──────────────┐
│  Speaker A   │  ← Top panel (face-tracked)
│   (Active)   │
├──────────────┤
│  Speaker B   │  ← Bottom panel (dimmed if inactive)
│  (Inactive)  │
└──────────────┘
```

### Basic Usage

```bash
# Permanent split-screen (audio-based, needs HF_TOKEN)
python main.py --url "PODCAST_URL" --split-screen

# Dynamic split (auto-toggle between full and split)
python main.py --url "PODCAST_URL" --split-screen --dynamic-split

# Visual-based trigger (NO TOKEN REQUIRED!)
python main.py --url "PODCAST_URL" --split-screen --dynamic-split --split-trigger face
```

### Split Trigger Modes

| Trigger | Flag | Token Required | Dimming Effect | How It Works |
|---|---|---|---|---|
| **Diarization** (default) | `--split-trigger diarization` | ✅ `HF_TOKEN` | ✅ Yes | Uses audio to detect who is speaking |
| **Face** | `--split-trigger face` | ❌ No | ❌ No | Uses visual face count (2+ faces = split) |

> **Tip:** Use `--split-screen --dynamic-split --split-trigger face` for the fastest rendering without any API tokens.

### Split-Screen Optimization

#### Auto-Zoom (`--split-auto-zoom`)
Dynamically adjusts the zoom level of each panel to keep framing tight on the speaker and exclude other faces. Essential when speakers sit close together.

```bash
python main.py --url "PODCAST_URL" \
  --split-screen --dynamic-split --split-trigger face \
  --split-auto-zoom --split-v-align 0.4
```

| Parameter | Flag | Default | Description |
|---|---|---|---|
| Manual Zoom | `--split-zoom` | `1.0` | Static zoom factor for all panels |
| Vertical Align | `--split-v-align` | `0.5` | 0.0 = top, 0.5 = center, 1.0 = bottom |
| Auto-Zoom | `--split-auto-zoom` | off | AI-driven zoom per panel |
| Max Zoom | `--split-max-zoom` | `2.5` | Maximum zoom limit |

---

## Mode 2: Camera Switch (`--camera-switch`)

Mimics professional editing by focusing only on the active speaker in full screen, switching between them cinematically.

```
Scene 1: Speaker A talking         Scene 2: Speaker B responds
┌──────────────┐                   ┌──────────────┐
│              │                   │              │
│  Speaker A   │   ──── CUT ────→  │  Speaker B   │
│  (Full 9:16) │                   │  (Full 9:16) │
│              │                   │              │
└──────────────┘                   └──────────────┘
```

### Basic Usage

```bash
# Standard camera switch
python main.py --url "PODCAST_URL" --camera-switch

# With longer hold duration (prevents flickering)
python main.py --url "PODCAST_URL" --camera-switch --switch-hold-duration 3.0

# 3-speaker podcast
python main.py --url "PODCAST_URL" --camera-switch --diarization-speakers 3
```

### How Camera Switch Renders

| Scenario | Rendering |
|---|---|
| **1 speaker active** | Full 9:16 crop following that speaker's face |
| **2+ speakers active, same scene** | **Blurred Pillarbox** — original 16:9 frame centered with blurred background |
| **2+ speakers active, different scenes** | Stays focused on current speaker (no pillarbox) |
| **No one speaking** | Holds on last active speaker |

### Hold Duration

The `--switch-hold-duration` parameter (default: `2.0` seconds) prevents the camera from switching too quickly during rapid dialogue. Increase it for calmer conversations, decrease it for high-energy debates.

---

## Multi-Speaker Support (3+ Speakers)

Both modes support 3 or more speakers across multiple scenes.

### Speaker Detection

| Mode | Flag | Description |
|---|---|---|
| Auto-detect | `--diarization-speakers auto` (default) | Visual scan of 20 frames to auto-count speakers |
| Fixed count | `--diarization-speakers 3` | Manually specify exact speaker count |

```bash
# 3-speaker podcast with camera switch
python main.py --url "PODCAST_URL" \
  --camera-switch \
  --diarization-speakers 3
```

### How 3+ Speakers Work in Split-Screen

- The screen is always divided into **2 panels** (top & bottom)
- Panels swap between speakers based on who is active
- Each speaker has their own **frozen frame fallback** — when not visible in the current scene, the panel shows their last valid frame

---

## Requirements

### HuggingFace Token Setup

1. Create an account at [HuggingFace](https://huggingface.co/)
2. Create an access token at [Settings → Tokens](https://huggingface.co/settings/tokens)
3. Accept the [Pyannote Speaker Diarization 3.1 agreement](https://huggingface.co/pyannote/speaker-diarization-3.1)
4. Add to your `.env` file:
   ```
   HF_TOKEN=hf_your-token-here
   ```

> **Note:** `--split-trigger face` mode does **not** require `HF_TOKEN`.

---

## Recommended Configurations

### Quick & Token-Free
```bash
python main.py --url "PODCAST_URL" \
  --split-screen --dynamic-split --split-trigger face \
  --face-detector yolo
```

### Best Quality (With Token)
```bash
python main.py --url "PODCAST_URL" \
  --split-screen --dynamic-split \
  --split-trigger diarization \
  --split-auto-zoom \
  --face-detector yolo
```

### Cinematic Interview
```bash
python main.py --url "PODCAST_URL" \
  --camera-switch \
  --switch-hold-duration 2.5 \
  --face-detector yolo
```

---

## See Also

- [Face Tracking & Auto-Framing](Face-Tracking-and-Auto-Framing) — Tracking parameter tuning
- [CLI Reference](CLI-Reference) — All split-screen and camera-switch flags

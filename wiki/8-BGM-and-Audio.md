# 🎵 BGM & Audio

OpenSource Clipping includes an automatic background music (BGM) system with two professional mixing modes.

---

## How It Works

1. Gemini AI analyzes the clip content and suggests a **mood** (e.g., `chill`, `epic`, `sad`, `upbeat`, `suspense`)
2. The system picks a random MP3 from the matching mood folder in `assets/bgm/`
3. BGM is mixed with the clip audio using the selected mixing mode
4. If the MP3 is shorter than the video, it's **auto-looped** seamlessly

---

## BGM Mixing Modes

### Sidechain Ducking (Default)

BGM volume automatically lowers when the speaker is talking, then rises during pauses. This provides a professional effect like premium podcasts and YouTube videos.

```bash
python main.py --url "VIDEO_URL" --bgm-mode ducking
```

### Constant Background

BGM plays at a stable, low volume throughout the video without any dynamic adjustments. Best for content with few pauses.

```bash
python main.py --url "VIDEO_URL" --bgm-mode background
```

### Disable BGM

```bash
python main.py --url "VIDEO_URL" --no-bgm
```

---

## BGM Folder Setup

Place your royalty-free `.mp3` files into the mood folders:

```text
assets/
└── bgm/
    ├── chill/          # Relaxed / lofi music
    │   ├── song1.mp3
    │   └── song2.mp3
    ├── epic/           # Cinematic / action music
    │   └── trailer.mp3
    ├── sad/            # Emotional / melancholic music
    │   └── piano.mp3
    ├── suspense/       # Mystery / tension music
    │   └── dark.mp3
    └── upbeat/         # Energetic / happy music
        └── pop.mp3
```

### Rules

- You can place **multiple MP3s** in each folder — the system picks one **randomly** each time
- If the requested mood folder is empty, the system falls back to `chill/`
- If `chill/` is also empty, BGM is skipped entirely (same as `--no-bgm`)
- MP3 files shorter than the video are **auto-looped** (`-stream_loop -1`)

---

## Recommended BGM Sources (Free & Royalty-Free)

| Source | URL | Notes |
|---|---|---|
| **Pixabay Music** | [pixabay.com/music](https://pixabay.com/music/) | ⭐ Recommended — free, no attribution required |
| **YouTube Audio Library** | YouTube Studio → Audio Library | Safe from copyright strikes |
| **Incompetech** | [incompetech.com](https://incompetech.com/music/royalty-free/music.html) | Kevin MacLeod — usually requires attribution |

### Pixabay Direct Links

- [Chill](https://pixabay.com/music/search/mood/chill/)
- [Epic](https://pixabay.com/music/search/mood/epic/)
- [Upbeat](https://pixabay.com/music/search/mood/upbeat/)

---

## Technical Details

- Base BGM volume: `0.25` (25% of original volume)
- Ducking mode uses FFmpeg's `sidechaincompress` filter
- BGM is applied **after** segment trimming (if enabled) to ensure seamless audio across cuts

---

## See Also

- [CLI Reference](CLI-Reference) — `--bgm-mode`, `--no-bgm`
- [Hook V2 & Segment Trimming](Hook-V2-and-Segment-Trimming) — How BGM interacts with trimming

# 🚀 Getting Started

This guide walks you through setting up OpenSource Clipping on your local machine.

---

## 📋 Prerequisites

| Requirement | Details |
|---|---|
| **Python** | 3.10 or higher |
| **FFmpeg** | Must be installed and available in PATH |
| **GPU (CUDA)** | Recommended for Whisper transcription (CPU fallback available) |
| **Google Gemini API Key** | **Required** — [Get one here](https://aistudio.google.com/apikey) |
| **Pexels API Key** | Optional, for B-roll footage — [Get one here](https://www.pexels.com/api/) |
| **HuggingFace Token** | Optional, for split-screen / camera-switch — [Get one here](https://huggingface.co/settings/tokens) |

> **Note:** If you plan to use split-screen or camera-switch podcast modes, you must also accept the [Pyannote model agreement](https://huggingface.co/pyannote/speaker-diarization-3.1) on HuggingFace.

---

## 📥 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/NaufalRizqullah/opensource-clipping.git
cd opensource-clipping
```

### 2. Install Dependencies

Choose one of the following methods:

```bash
# Using pip (standard)
pip install -r requirements.txt

# Using uv (faster alternative)
uv sync
```

### 3. Set Up API Keys

```bash
# Copy the template
cp .env.sample .env
```

Then edit the `.env` file and add your API keys:

```env
GOOGLE_API_KEY=your-gemini-api-key-here
PEXELS_API_KEY=your-pexels-api-key-here      # Optional
HF_TOKEN=your-huggingface-token-here          # Optional (for podcast modes)
NVIDIA_API_KEY=your-nvidia-api-key-here       # Optional (for NVIDIA NIM provider)
```

### 4. Run Your First Clip

```bash
python main.py --url "https://youtube.com/watch?v=VIDEO_ID"
```

That's it! The pipeline will:
1. Download the video
2. Transcribe it with Whisper
3. Analyze it with Gemini AI
4. Generate highlight clips with subtitles, thumbnails, and metadata

---

## 📁 Output Structure

All generated files are saved in the `outputs/` directory:

```text
outputs/
└── <video_hash>/
    ├── highlight_rank_1_ready.mp4    # Final rendered clip (Rank 1)
    ├── highlight_rank_2_ready.mp4    # Final rendered clip (Rank 2)
    ├── thumbnail_rank_1.jpg          # Auto-generated thumbnail
    ├── thumbnail_rank_2.jpg
    ├── render_manifest.json          # Manifest with metadata for all clips
    ├── metadata_preview.json         # Gemini-generated metadata
    ├── gemini_response.json          # Raw AI response (for debugging)
    └── video_asli.mp4                # Downloaded source video
```

---

## 🎯 Quick Examples

### Standard Clipping (7 clips, vertical)
```bash
python main.py --url "VIDEO_URL" --clips 7 --ratio "9:16"
```

### Landscape Output (YouTube format)
```bash
python main.py --url "VIDEO_URL" --ratio "16:9" --clips 5
```

### Podcast with Split-Screen
```bash
python main.py --url "PODCAST_URL" --split-screen --dynamic-split --split-trigger face
```

### No Subtitles, No BGM (Clean output)
```bash
python main.py --url "VIDEO_URL" --no-subs --no-bgm --no-broll
```

---

## 🌐 Supported Video Sources

| Platform | Flag | Example |
|---|---|---|
| YouTube | `--source youtube` (default) | `--url "https://youtube.com/watch?v=..."` |
| TikTok | `--source tiktok` | `--url "https://www.tiktok.com/@user/video/..."` |
| Instagram | `--source instagram` | `--url "https://www.instagram.com/reel/..."` |
| Google Drive | `--source gdrive` | `--url "https://drive.google.com/file/d/..."` |

---

## ⬆️ Next Steps

- 📖 Read the full **[CLI Reference](CLI-Reference)** for all available options
- 🎙️ Learn about **[Podcast Modes](Podcast-Modes)** for multi-speaker content
- ☁️ No GPU? Check the **[Google Colab Guide](Google-Colab-Guide)**
